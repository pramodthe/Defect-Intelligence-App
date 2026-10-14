"""Explicit download of public local layout/table models; never reads private inputs."""
import json
from docling.utils.model_downloader import download_models
from app.store import digest
from app.settings import ROOT

target = ROOT / ".cache/models/docling"
download_models(output_dir=target,with_layout=True,with_tableformer=True,with_code_formula=False,
                with_picture_classifier=False,with_rapidocr=False,progress=True)
manifest = {"profile":"docling-layout-table/1","path":str(target),
            "files":{p.relative_to(target).as_posix():digest(p.read_bytes()) for p in target.rglob('*') if p.is_file() and '.cache' not in p.relative_to(target).parts}}
(ROOT/'data/docling-profile.json').write_text(json.dumps(manifest,indent=2),'utf-8')
print("Local layout/table model cache complete: " + str(target))
