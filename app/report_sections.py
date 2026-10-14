"""Restore original report sections around a saved run's retrieved passages.

This is a source view, not model-generated wording. Units come only from the
run's pinned publication; later extraction revisions cannot replace its text.
"""
import json
import re
from collections import defaultdict

from app.retrieval import manifest_chunks
from app.store import Store

STOP_WORDS = set("a an and are as at be by for from how in into is it of on or that the their this to using was were what which with "
                 "report imported original section relevant identify explain show keep exact wording cite citation citations "
                 "author authored reasoning finding findings defect defects proposed repair repairs recommendation recommendations "
                 "option options separate distinguish governing requirement requirements standard standards figure figures".split())


def query_words(value):
    words = re.findall(r"[\w]+", value.lower())
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word for word in words
            if word not in STOP_WORDS}


def original_report_sections(store: Store, run_id: str):
    run = store.require('SELECT question,manifest_id,evidence FROM runs WHERE id=?', (run_id,))
    evidence = json.loads(run['evidence']).get('items', [])
    chunk_ids, _ = manifest_chunks(store, run['manifest_id'])
    if not chunk_ids or not evidence:
        return {'sections': [], 'manifest_id': run['manifest_id'], 'warnings': [], 'wording': 'original_source'}
    rows = store.all('SELECT id,document_id,metadata FROM chunk_revisions WHERE id IN (' +
                     ','.join('?' for _ in chunk_ids) + ')', chunk_ids)
    pinned = {r['id']: {**r, 'metadata': json.loads(r['metadata'])} for r in rows}
    unit_groups = defaultdict(set)
    for row in pinned.values():
        meta = row['metadata']
        key = (row['document_id'], meta.get('defect_item_id') or meta['logical_unit_id'])
        unit_groups[key].add(meta['logical_unit_id'])
    matches = defaultdict(list)
    for item in evidence:
        record = pinned.get(item['id'])
        if record:
            meta = record['metadata']
            matches[(record['document_id'], meta.get('defect_item_id') or meta['logical_unit_id'])].append(item)
    unit_ids = sorted({uid for key in matches for uid in unit_groups[key]})
    if not unit_ids:
        return {'sections': [], 'manifest_id': run['manifest_id'],
                'warnings': ['No published report section could be linked to the saved passages'], 'wording': 'original_source'}
    units = store.all('SELECT u.*,p.block_ids FROM units u JOIN parents p ON p.id=u.parent_id WHERE u.id IN (' +
                      ','.join('?' for _ in unit_ids) + ')', unit_ids)
    # OCR is a separate derived extraction. It is never presented as original wording.
    block_ids = sorted({bid for u in units if u['purpose'] != 'visual_extract' for bid in json.loads(u['block_ids'])})
    blocks = store.all('SELECT id,document_id,sequence,text,kind,content_kind FROM blocks WHERE id IN (' +
                       ','.join('?' for _ in block_ids) + ')', block_ids) if block_ids else []
    by_block = {b['id']: b for b in blocks if b['content_kind'] != 'ocr_text'}
    anchors = store.all('SELECT id,block_id,start_cp,end_cp FROM anchors WHERE block_id IN (' +
                        ','.join('?' for _ in block_ids) + ') ORDER BY start_cp,end_cp DESC', block_ids) if block_ids else []
    by_anchor = defaultdict(list)
    for anchor in anchors:
        by_anchor[anchor['block_id']].append(anchor)
    media = store.all('SELECT id,block_id,asset_id,caption,role FROM media WHERE block_id IN (' +
                      ','.join('?' for _ in block_ids) + ')', block_ids) if block_ids else []
    by_media = defaultdict(list)
    for image in media:
        by_media[image['block_id']].append({**image, 'original_url': '/api/assets/' + image['asset_id'] + '/content'})
    terms = query_words(run['question'])
    sections = []
    warnings = []
    for (document_id, group_id), hits in matches.items():
        doc = store.require('SELECT filename,asset_id,role FROM documents WHERE id=?', (document_id,))
        doc['role'] = pinned[hits[0]['id']]['metadata'].get('source_role', doc['role'])
        item = store.one('SELECT title,heading_anchor_id FROM items WHERE id=? AND document_id=?', (group_id, document_id))
        whole_section = bool(item and item['title'] != 'Document context' and doc['role'] == 'company_report')
        # A reference book/document context is not one defect-report section.
        # Keep only complete paragraphs actually returned by retrieval in that case.
        hit_blocks = {segment['block_id'] for hit in hits
                      for segment in pinned[hit['id']]['metadata'].get('source_segments', [])}
        parts = []
        matched_units = {pinned[e['id']]['metadata']['logical_unit_id'] for e in hits}
        for unit in units:
            if unit['id'] not in unit_groups[(document_id, group_id)] or unit['purpose'] == 'visual_extract':
                continue
            passages = []
            for bid in json.loads(unit['block_ids']):
                b = by_block.get(bid)
                if not b or not (b['text'].strip() or by_media[bid]) or (not whole_section and bid not in hit_blocks):
                    continue
                exact = next((a for a in by_anchor[bid] if a['start_cp'] == 0 and a['end_cp'] == len(b['text'])), None)
                if not exact:
                    warnings.append('A source block lacks a complete original anchor; inspect the preserved document')
                    continue
                passages.append({**b, 'anchor_id': exact['id'], 'media': by_media[bid]})
            if not passages:
                continue
            finding = store.one('SELECT identifier,location FROM findings WHERE id=?', (unit['finding_id'],)) if unit['finding_id'] else None
            parts.append({'id': unit['id'], 'purpose': unit['purpose'], 'scope': unit['scope_state'],
                          'finding': finding, 'option_id': unit['option_id'], 'matched': unit['id'] in matched_units,
                          'blocks': passages, 'sequence': min(b['sequence'] for b in passages)})
        parts.sort(key=lambda p: (p['sequence'], p['id']))
        if not parts:
            continue
        title = item['title'] if whole_section and item else 'Retrieved source passages'
        native_text = '\n'.join(b['text'] for p in parts for b in p['blocks'])
        direct = sum(any(m != 'qualified_graph_source' for m in e.get('retrieval_methods', [])) for e in hits)
        score = 4 * len(query_words(title) & terms) + len(query_words(native_text) & terms)
        sections.append({'id': group_id, 'document_id': document_id, **doc, 'title': title,
                         'heading_anchor_id': item['heading_anchor_id'] if whole_section and item else None,
                         'parts': parts, 'retrieved_passages': len(hits), 'direct_search_passages': direct,
                         'sequence': min(p['sequence'] for p in parts), 'relevance': score,
                         'scope': 'published_report_section' if whole_section else 'retrieved_source_passages'})
    sections.sort(key=lambda s: (-s['relevance'], -s['direct_search_passages'], -s['retrieved_passages'], s['sequence']))
    return {'sections': sections, 'manifest_id': run['manifest_id'], 'wording': 'original_source',
            'warnings': list(dict.fromkeys(warnings))}
