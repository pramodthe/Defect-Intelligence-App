import io
import json
import mimetypes
import posixpath
import re
import time
from pathlib import Path
from typing import Any, cast
from zipfile import BadZipFile, ZipFile

from lxml import etree
from PIL import Image

from app.contracts import DocumentIR, Locator, SourceBlock
from app.store import Store, canonical, digest, identity

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "v": "urn:schemas-microsoft-com:vml", "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PARSER = "ooxml-ordered/1"


def normalize_pdf_box(bounds, page_box, rotation=0):
    left, bottom, right, top = page_box
    width, height = right - left, top - bottom
    points = []
    for px in [bounds[0], bounds[2]]:
        for py in [bounds[1], bounds[3]]:
            x, y = (px - left) / width, (top - py) / height
            x, y = {0: (x, y), 90: (1-y, x), 180: (1-x, 1-y), 270: (y, 1-x)}[rotation % 360]
            points.append((max(0, min(1, x)), max(0, min(1, y))))
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def validate_upload(data: bytes, filename: str, store: Store) -> str:
    if len(data) > store.config.upload_limit_mb * 1024**2:
        raise ValueError("File exceeds configured upload limit")
    suffix = Path(filename).suffix.lower()
    if suffix == ".doc":
        raise ValueError("Legacy DOC requires a configured local conversion adapter; save a DOCX rendition")
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix != ".docx":
        raise ValueError("Unsupported or mismatched file type; use DOCX or PDF")
    try:
        with ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > store.config.max_archive_entries:
                raise ValueError("Too many archive entries")
            if sum(i.file_size for i in infos) > store.config.expanded_limit_mb * 1024**2:
                raise ValueError("DOCX expanded-size limit exceeded")
            for info in infos:
                if info.flag_bits & 1 or info.filename.startswith(("/", "\\")) or ".." in info.filename.replace("\\", "/").split("/"):
                    raise ValueError("Unsafe DOCX archive entry")
            if "word/document.xml" not in z.namelist():
                raise ValueError("Missing Word document part")
    except BadZipFile as exc:
        raise ValueError("Malformed DOCX archive") from exc
    return DOCX_MIME


def register(data: bytes, filename: str, role: str, store: Store, family_id: str | None = None,
             metadata: dict | None = None) -> dict:
    if role not in {"company_report", "original_reference", "project_evidence"}:
        raise ValueError("Unknown source role")
    mime = validate_upload(data, filename, store)
    sha = digest(data)
    existing = store.one("SELECT * FROM documents WHERE sha256=?", (sha,))
    if existing:
        job = store.require("SELECT * FROM jobs WHERE document_id=? ORDER BY created DESC LIMIT 1", (existing["id"],))
        return {"document_id": existing["id"], "job_id": job["id"], "duplicate": True}
    asset_id = store.asset(data, mime, "originals", {"original_filename": Path(filename).name})
    doc_id = identity("doc", sha)
    if family_id and not store.one("SELECT id FROM families WHERE id=?", (family_id,)):
        raise ValueError("Unknown family; revisions must be linked explicitly")
    family_id = family_id or identity("family", sha)
    job_id = identity("job", doc_id, "ingestion/1")
    with store.connect() as con:
        store.insert("families", {"id": family_id, "label": Path(filename).name}, con)
        store.insert("documents", {"id": doc_id, "family_id": family_id, "asset_id": asset_id,
                                   "sha256": sha, "filename": Path(filename).name, "role": role,
                                   "status": "queued", "created": time.time(), "metadata": metadata or {}}, con)
        store.insert("jobs", {"id": job_id, "document_id": doc_id, "status": "queued", "created": time.time(),
                              "graph_version": "ingestion/1"}, con)
    store.event(job_id, "queued", {"document_id": doc_id})
    return {"document_id": doc_id, "job_id": job_id, "duplicate": False}


def parse_docx(store: Store, document: dict) -> DocumentIR:
    data = store.asset_path(document["asset_id"]).read_bytes()
    validate_upload(data, document["filename"], store)
    doc_id = document["id"]
    structure_id = identity("structure", doc_id, PARSER)
    blocks: list[SourceBlock] = []
    assets = {document["asset_id"]}
    warnings = []
    # python-docx validates the OPC package; lxml supplies precise mixed/nested OOXML traversal.
    from docx import Document
    Document(io.BytesIO(data))
    with ZipFile(io.BytesIO(data)) as z:
        media_names = [n for n in z.namelist() if n.startswith("word/media/") and not n.endswith("/")]
        media_assets = {}
        for name in media_names:
            raw = z.read(name)
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            metadata: dict[str, Any] = {"package_path": name, "method": "original_ooxml_asset"}
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    metadata.update({"width": im.width, "height": im.height})
                    if im.width * im.height > store.config.max_pixels:
                        metadata["warning"] = "Decode pixel limit exceeded; original preserved"
            except Exception:
                metadata["warning"] = "Preview/OCR unsupported for this preserved original format"
            aid = store.asset(raw, mime, "media", metadata)
            media_assets[name] = aid
            assets.add(aid)
        styles = {}
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        if "word/styles.xml" in z.namelist():
            sx = etree.fromstring(z.read("word/styles.xml"), parser)
            for style in sx.xpath("//w:style", namespaces=NS):
                sid = style.get("{" + NS["w"] + "}styleId")
                outline = style.xpath("./w:pPr/w:outlineLvl/@w:val", namespaces=NS)
                name = style.xpath("./w:name/@w:val", namespaces=NS)
                styles[sid] = {"outline": int(outline[0]) if outline else None, "name": name[0] if name else sid}
        inventory: dict[str, Any] = {"media": media_names, "relationships": {}}
        parts = ["word/document.xml"] + sorted(n for n in z.namelist() if re.match(r"word/(header|footer)\d+\.xml$", n))
        for part in parts:
            tree = etree.fromstring(z.read(part), parser)
            tree_root = tree.getroottree()
            relpath = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            rels = {}
            if relpath in z.namelist():
                reltree = etree.fromstring(z.read(relpath), parser)
                for rel in reltree:
                    rels[rel.get("Id")] = dict(rel.attrib)
            inventory["relationships"][part] = rels
            heading_path: list[str] = []
            ordinal = 0

            def emit(element, kind, parent, order, text="", payload=None, table_path=None, rid=None):
                xpath = tree_root.getpath(element)
                bid = identity("block", structure_id, part, xpath, kind, order)
                locator = Locator(document_version_id=doc_id, format="docx", xml_part=part, xpath=xpath,
                                  paragraph_ordinal=ordinal if kind in {"paragraph", "heading", "list_item", "picture_occurrence", "text_box"} else None,
                                  table_path=table_path or [], relationship_id=rid, heading_path=list(heading_path))
                block = SourceBlock(block_id=bid, document_version_id=doc_id, parent_block_id=parent,
                                    kind=kind, order_key=order, text=text, locator=locator, payload=payload or {})
                blocks.append(block)
                return block

            def walk(element, parent=None, order=None, table_path=None):
                nonlocal ordinal, heading_path
                order = order or [len(blocks)]
                table_path = table_path or []
                local = etree.QName(element).localname
                if local == "p":
                    ordinal += 1
                    texts = []
                    for node in element.iter():
                        # Text boxes are their own blocks; do not duplicate nested paragraph text.
                        nearest_p = next((a for a in node.iterancestors() if etree.QName(a).localname == "p"), None)
                        if nearest_p is not element:
                            continue
                        tag = etree.QName(node).localname
                        if tag == "t":
                            texts.append(node.text or "")
                        elif tag == "tab":
                            texts.append("\t")
                        elif tag in {"br", "cr"}:
                            texts.append("\n")
                    text = "".join(texts)
                    style_ids = element.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS)
                    style_id = style_ids[0] if style_ids else ""
                    style = styles.get(style_id, {})
                    level = style.get("outline")
                    if level is None and re.match(r"Heading[1-9]$", style_id, re.I):
                        level = int(style_id[-1]) - 1
                    numbering = element.xpath("./w:pPr/w:numPr/*/@w:val", namespaces=NS)
                    kind = "heading" if level is not None else "list_item" if numbering else "paragraph"
                    if level is not None and text.strip():
                        heading_path = heading_path[:level] + [text.strip()]
                    b = emit(element, kind, parent, order, text, {"style_id": style_id, "heading_level": level,
                             "numbering": numbering, "part_scope": "body" if part == "word/document.xml" else "header_footer"}, table_path)
                    images = element.xpath(".//a:blip | .//v:imagedata", namespaces=NS)
                    for index, pic in enumerate(images):
                        rid = pic.get("{" + NS["r"] + "}embed") or pic.get("{" + NS["r"] + "}id")
                        rel = rels.get(rid, {})
                        target = posixpath.normpath(posixpath.join(posixpath.dirname(part), rel.get("Target", "")))
                        aid = media_assets.get(target)
                        if rel.get("TargetMode") == "External" or not aid:
                            b.warnings.append("Missing/external image relationship; no network retrieval")
                            continue
                        crop = pic.getparent().xpath(".//a:srcRect/@*", namespaces=NS)
                        alt = element.xpath(".//wp:docPr/@descr | .//wp:docPr/@title", namespaces=NS)
                        mb = emit(pic, "picture_occurrence", b.block_id, order + [index], "",
                                  {"asset_id": aid, "media_occurrence_id": identity("media", doc_id, part, tree_root.getpath(pic)),
                                   "alt_text": " ".join(alt), "crop": crop,
                                   "floating": bool(element.xpath(".//wp:anchor", namespaces=NS)),
                                   "caption_state": "unresolved", "source_identification": "unknown"}, table_path, rid)
                        if mb.payload["floating"]:
                            mb.warnings.append("Floating drawing reading order requires review")
                        if crop:
                            mb.warnings.append("Word drawing has crop; original un-cropped asset preserved")
                    for index, box in enumerate(element.xpath(".//w:txbxContent", namespaces=NS)):
                        tb = emit(box, "text_box", b.block_id, order + [900, index], "", {}, table_path)
                        for child_index, child in enumerate(box):
                            walk(child, tb.block_id, order + [900, index, child_index], table_path)
                elif local in {"tbl", "tr", "tc"}:
                    kind = {"tbl": "table", "tr": "row", "tc": "cell"}[local]
                    span = element.xpath("./w:tcPr/w:gridSpan/@w:val | ./w:tcPr/w:vMerge/@w:val", namespaces=NS)
                    b = emit(element, kind, parent, order, "", {"cell_spans": span}, table_path)
                    for index, child in enumerate(element):
                        if etree.QName(child).localname in {"p", "tbl", "tr", "tc"}:
                            walk(child, b.block_id, order + [index], table_path + [index])
                else:
                    for index, child in enumerate(element):
                        walk(child, parent, order + [index], table_path)

            walk(tree)
        store.asset(canonical(inventory).encode(), "application/json", "derived",
                    {"document_id": doc_id, "method": "ooxml_inventory"})
        warnings.append("Image captions/associations are candidates until source-supported review; no Word pages inferred")
    return DocumentIR(document_version_id=doc_id, structure_revision_id=structure_id,
                      original_asset_id=document["asset_id"], parser_profile_id=PARSER,
                      root_block_ids=[b.block_id for b in blocks if not b.parent_block_id],
                      blocks=blocks, asset_ids=sorted(assets), warnings=warnings)


def parse_pdf(store: Store, document: dict) -> DocumentIR:
    import pypdfium2 as pdfium
    path = store.asset_path(document["asset_id"])
    pdf = pdfium.PdfDocument(path)
    if len(pdf) > store.config.max_pdf_pages:
        raise ValueError("PDF page limit exceeded")
    doc_id = document["id"]
    profile = "pdfium-native-region/2"
    sid = identity("structure", doc_id, profile, store.config.docling_artifacts_path)
    blocks = []
    assets = {document["asset_id"]}
    warnings = []
    if store.config.docling_artifacts_path:
        # A configured local cache prevents Docling from fetching processing models implicitly.
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        opts = PdfPipelineOptions(artifacts_path=Path(store.config.docling_artifacts_path))
        import rapidocr
        ocr_models = Path(rapidocr.__file__).parent / "models"
        opts.ocr_options = RapidOcrOptions(lang=["ch"],
            det_model_path=str(ocr_models / "PP-OCRv6_det_small.onnx"),
            rec_model_path=str(ocr_models / "PP-OCRv6_rec_small.onnx"),
            cls_model_path=str(ocr_models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"))
        opts.enable_remote_services = False
        result = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}).convert(path)
        raw = result.document.export_to_dict()
        store.asset(canonical(raw).encode(), "application/json", "derived", {"document_id": doc_id, "method": "docling"})
        for index, (parsed_item, level) in enumerate(result.document.iterate_items()):
            item = cast(Any, parsed_item)
            for pi, prov in enumerate(getattr(item, "prov", [])):
                page = pdf[prov.page_no - 1]
                page_box = list(page.get_cropbox())
                w, h = page_box[2]-page_box[0], page_box[3]-page_box[1]
                box = prov.bbox
                raw_box = [box.l, box.t, box.r, box.b]
                is_bottom = "BOTTOM" in str(box.coord_origin).upper()
                pdf_bounds = [box.l, min(box.t, box.b), box.r, max(box.t, box.b)] if is_bottom else [box.l, h-max(box.t, box.b), box.r, h-min(box.t, box.b)]
                loc = Locator(document_version_id=doc_id, format="pdf", page_index=prov.page_no - 1,
                              raw_bbox=raw_box, normalized_bbox=normalize_pdf_box(pdf_bounds,page_box,page.get_rotation()),
                              rotation=page.get_rotation(), page_box=page_box)
                label = str(item.label).split(".")[-1].lower()
                text = getattr(item, "text", "")
                payload = {"docling_ref": item.self_ref, "hierarchy_level": level, "provenance": prov.model_dump(mode="json")}
                if label == "table":
                    text = item.export_to_markdown(doc=result.document)
                    payload["cells"] = item.data.model_dump(mode="json")
                blocks.append(SourceBlock(block_id=identity("block", sid, index, pi), document_version_id=doc_id,
                    kind="table" if label == "table" else "heading" if label=='section_header' else "paragraph", order_key=[index, pi], text=text,
                    extraction_kind="table_serialization" if label == "table" else "native_text", locator=loc, payload=payload))
        profile = "docling-pdf/1"
    else:
        warnings.append("Docling layout cache not configured: native PDFium page text only; complex layout/table scope needs review")
    for index in range(len(pdf)):
        page = pdf[index]
        w, h = page.get_size()
        if w * h * 4 > store.config.max_pixels:
            raise ValueError("PDF render pixel limit exceeded")
        tp = page.get_textpage()
        text = tp.get_text_range()
        page_box = list(page.get_cropbox())
        for image_index, obj in enumerate(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])):
            try:
                px_w, px_h = obj.get_px_size()
                if px_w * px_h > store.config.max_pixels:
                    warnings.append("Embedded PDF image decode limit exceeded; preserved PDF remains available")
                    continue
                filters = obj.get_filters()
                raw_stream_id = store.asset(bytes(obj.get_data()), "application/octet-stream", "media",
                    {"document_id":doc_id,"page_index":index,"object_index":image_index,"filters":filters,"method":"original_pdf_image_stream"})
                assets.add(raw_stream_id)
                extracted = io.BytesIO()
                obj.extract(extracted, fb_format="png")
                pixels = extracted.getvalue()
                with Image.open(io.BytesIO(pixels)) as im:
                    mime = Image.MIME.get(im.format or "PNG", "image/png")
                aid = store.asset(pixels, mime, "media", {"method":"pdfium_image_extraction/1","raw_stream_asset_id":raw_stream_id,
                    "document_id":doc_id,"page_index":index,"filters":filters})
                assets.add(aid)
                bounds = list(obj.get_bounds())
                bid = identity("block",sid,index,"image",image_index)
                blocks.append(SourceBlock(block_id=bid,document_version_id=doc_id,kind="picture_occurrence",order_key=[index,2,image_index],
                    locator=Locator(document_version_id=doc_id,format="pdf",page_index=index,rotation=page.get_rotation(),page_box=page_box,
                        raw_bbox=bounds,normalized_bbox=normalize_pdf_box(bounds,page_box,page.get_rotation())),
                    payload={"asset_id":aid,"media_occurrence_id":identity("media",doc_id,index,"image",image_index),
                        "raw_stream_asset_id":raw_stream_id,"needs_ocr":True,"rendered_region":False},
                    warnings=["Raw stream and original PDF preserved; extracted raster may omit masks/vector annotations; inspect full page"] ))
            except Exception as exc:
                warnings.append("Embedded PDF image extraction incomplete: " + type(exc).__name__)
        if not store.config.docling_artifacts_path:
            root_id=identity("block",sid,index,"text")
            blocks.append(SourceBlock(block_id=root_id, document_version_id=doc_id,
                kind="page_region", order_key=[index, 0], text=text,
                locator=Locator(document_version_id=doc_id, format="pdf", page_index=index, rotation=page.get_rotation(),
                    page_box=[0, 0, w, h], raw_bbox=[0, 0, w, h], normalized_bbox=[0, 0, 1, 1]),
                payload={'has_text_children':bool(text)},
                warnings=["Page-wide native text locator; fine layout requires configured Docling"] if text else []))
            start=0
            for line_index,line in enumerate(text.splitlines(keepends=True)):
                blocks.append(SourceBlock(block_id=identity('block',sid,index,'line',line_index),document_version_id=doc_id,
                    parent_block_id=root_id,kind='paragraph',order_key=[index,0,line_index],text=line,
                    locator=Locator(document_version_id=doc_id,format='pdf',page_index=index,rotation=page.get_rotation(),
                        raw_bbox=page_box,normalized_bbox=[0,0,1,1],page_box=page_box),
                    payload={'parent_start_cp':start,'parent_end_cp':start+len(line),'layout_scope':'native_line_candidate'},
                    warnings=['Line source range preserved; page-wide bounds until reviewed layout extraction']))
                start+=len(line)
        # Full page rendition retains combined vector drawings, labels and annotations.
        bitmap = page.render(scale=1.5)
        im = bitmap.to_pil()
        out = io.BytesIO()
        im.save(out, format="PNG")
        aid = store.asset(out.getvalue(), "image/png", "media", {"method": "pdfium_page_rendition/1", "page_index": index, "scale": 1.5})
        assets.add(aid)
        bid = identity("block", sid, index, "visual")
        blocks.append(SourceBlock(block_id=bid, document_version_id=doc_id, kind="picture_occurrence",
            order_key=[index, 1], locator=Locator(document_version_id=doc_id, format="pdf", page_index=index,
                page_box=[0, 0, w, h], rotation=page.get_rotation(), normalized_bbox=[0, 0, 1, 1], raw_bbox=[0, 0, w, h]),
            payload={"asset_id": aid, "media_occurrence_id": identity("media", doc_id, index, "page"),
                     "needs_ocr": not bool(text.strip()), "rendered_region": True},
            warnings=["Rendered page, not an extracted original image; open preserved PDF for original context"]))
        tp.close()
        bitmap.close()
        page.close()
    pdf.close()
    return DocumentIR(document_version_id=doc_id, structure_revision_id=sid, original_asset_id=document["asset_id"],
        parser_profile_id=profile, root_block_ids=[b.block_id for b in blocks], blocks=blocks,
        asset_ids=sorted(assets), warnings=warnings)


def persist_ir(store: Store, ir: DocumentIR):
    raw = ir.model_dump(mode="json")
    asset_id = store.asset(canonical(raw).encode("utf-8"), "application/json", "derived",
                           {"document_id": ir.document_version_id, "method": ir.parser_profile_id})
    with store.connect() as con:
        store.insert("structures", {"id": ir.structure_revision_id, "document_id": ir.document_version_id,
            "ir_asset_id": asset_id, "profile": ir.parser_profile_id, "hash": digest(raw), "state": "validated"}, con)
        for index, b in enumerate(ir.blocks):
            store.insert("blocks", {"id": b.block_id, "document_id": ir.document_version_id,
                "structure_id": ir.structure_revision_id, "parent_id": b.parent_block_id, "kind": b.kind,
                "sequence": index, "text": b.text, "content_kind": b.extraction_kind,
                "locator": b.locator.model_dump(mode="json"), "payload": {**b.payload, "warnings": b.warnings}}, con)
            anchor_id = identity("anchor", b.block_id, 0, len(b.text))
            store.insert("anchors", {"id": anchor_id, "document_id": ir.document_version_id,
                "block_id": b.block_id, "start_cp": 0, "end_cp": len(b.text), "quote_hash": digest(b.text)}, con)
            if b.kind == "picture_occurrence":
                store.insert("media", {"id": b.payload["media_occurrence_id"], "asset_id": b.payload["asset_id"],
                    "document_id": ir.document_version_id, "block_id": b.block_id, "caption": b.payload.get("alt_text", ""),
                    "role": "unknown", "identity_json": {}, "warnings": b.warnings}, con)
    return {"structure_id": ir.structure_revision_id, "block_count": len(ir.blocks), "asset_count": len(ir.asset_ids), "warnings": ir.warnings}


_ocr_engine = None


def ocr_media(store: Store, document_id: str, owner_id: str):
    global _ocr_engine
    from rapidocr import RapidOCR
    if _ocr_engine is None:
        import rapidocr
        root = Path(rapidocr.__file__).parent / "models"
        paths = {"Det.model_path":root/"PP-OCRv6_det_small.onnx", "Rec.model_path":root/"PP-OCRv6_rec_small.onnx",
                 "Cls.model_path":root/"ch_ppocr_mobile_v2.0_cls_mobile.onnx"}
        if any(not p.is_file() for p in paths.values()):
            raise RuntimeError("Locked local OCR artifacts unavailable; explicit setup required")
        _ocr_engine = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                      "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                                      **{key:str(path) for key,path in paths.items()}})
    media = store.all("SELECT m.*,b.locator,b.payload FROM media m JOIN blocks b ON b.id=m.block_id WHERE m.document_id=?", (document_id,))
    completed = 0
    for m in media:
        visual_id = identity("visual", m["id"], m["asset_id"], "rapidocr-local/1")
        if store.one("SELECT id FROM visuals WHERE id=?", (visual_id,)):
            completed += 1
            continue
        if store.require("SELECT cancel FROM jobs WHERE id=?", (owner_id,))["cancel"]:
            raise RuntimeError("cancelled")
        payload = json.loads(m["payload"])
        warnings = json.loads(m["warnings"])
        if payload.get("rendered_region") and not payload.get("needs_ocr"):
            store.insert("visuals", {"id": visual_id, "media_id": m["id"], "text": "", "regions": [],
                "method": "native_page_available", "profile": "rapidocr-local/1", "warnings": warnings})
            continue
        try:
            with Image.open(store.asset_path(m["asset_id"])) as im:
                if im.width * im.height > store.config.max_pixels:
                    raise ValueError("Decode pixel limit exceeded")
                # Original bytes remain untouched; a bounded RGB rendition is local processing input.
                import numpy as np
                pixels = np.asarray(im.convert("RGB"))
            cached = store.one("SELECT v.* FROM visuals v JOIN media m ON m.id=v.media_id WHERE m.asset_id=? AND v.method='rapidocr' LIMIT 1", (m["asset_id"],))
            if cached:
                text, regions = cached["text"], json.loads(cached["regions"])
            else:
                result: Any = _ocr_engine(pixels)
                texts = list(result.txts or [])
                scores = list(result.scores or [])
                boxes = result.boxes.tolist() if result.boxes is not None else []
                text = "\n".join(texts)
                regions = [{"text": t, "confidence": float(s), "bbox": box} for t, s, box in zip(texts, scores, boxes, strict=False)]
            if any(r["confidence"] < .90 for r in regions):
                warnings.append("OCR uncertainty; numbers/years require visual review")
            warnings.append("Embedded/page extract may omit notes; original reference not verified")
            method = "rapidocr"
        except Exception as exc:
            text, regions, method = "", [], "unavailable"
            warnings.append("Local OCR unavailable: " + type(exc).__name__)
        store.insert("visuals", {"id": visual_id, "media_id": m["id"], "text": text, "regions": regions,
                                  "method": method, "profile": "rapidocr-local/1", "warnings": warnings})
        role = "standard_extract" if re.search(r"\bAS\s*\d{4}", text, re.I) else "code_extract" if re.search(r"NCC|BCA|BUILDING CODE", text, re.I) else "figure" if re.search(r"FIGURE|DRAWING", text, re.I) else "unknown"
        store.execute("UPDATE media SET role=?,warnings=? WHERE id=?", (role, canonical(warnings), m["id"]))
        completed += 1
        if completed % 10 == 0 or completed == len(media):
            store.event(owner_id, "ocr_progress", {"completed": completed, "total": len(media)})
    return {"visual_count": completed, "total": len(media)}
