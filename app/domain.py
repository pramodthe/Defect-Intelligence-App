"""Immutable, source-qualified domain instances; search aliases remain a separate layer."""
import json
import re
import time
from collections import Counter
from typing import TYPE_CHECKING

from app.store import Store, digest, identity

if TYPE_CHECKING:
    from app.ontology import Ontology


def option_number(text: str) -> str | None:
    match = re.search(r'(?:^Option\s*(\d+)\b|^Alternatively,?\s*Option\s*(\d+)\b|\bas\s+Option\s*(\d+)\b)',text.strip(),re.I)
    return next((v for v in match.groups() if v),None) if match else None


def option_segments(blocks: list[tuple[str,str]]) -> list[tuple[str | None,list[str]]]:
    markers = [(index,option_number(text)) for index,(_,text) in enumerate(blocks) if option_number(text)]
    if len({number for _,number in markers})<2:
        return [(markers[0][1] if markers else None,[bid for bid,_ in blocks])]
    return [(number,[bid for bid,_ in blocks[start:markers[index+1][0] if index+1<len(markers) else len(blocks)]])
            for index,(start,number) in enumerate(markers)]


def ancestors(model: dict, class_id: str) -> set[str]:
    classes = {c['id']: c for c in model['classes']}
    result = set()
    while class_id:
        if class_id in result or class_id not in classes:
            raise ValueError('Invalid domain class hierarchy')
        result.add(class_id)
        class_id = classes[class_id]['parent']
    return result


def validate_snapshot(store: Store, snapshot: dict, model: dict):
    records = {r['id']: r for r in snapshot['records']}
    if len(records) != len(snapshot['records']):
        raise ValueError('Duplicate domain record identity')
    classes = {c['id']: c for c in model['classes']}
    predicates = {r['id']: r for r in model['relationships']}
    doc = store.require('SELECT * FROM documents WHERE id=?', (snapshot['document_id'],))
    owned = {a['id'] for a in store.all('SELECT id FROM anchors WHERE document_id=?', (doc['id'],))}
    blocks = {b['id'] for b in store.all('SELECT id FROM blocks WHERE document_id=?', (doc['id'],))}
    for record in records.values():
        lineage = ancestors(model, record['class_id'])
        if any(len(lineage.intersection(group)) > 1 for group in model['disjoint_sets']):
            raise ValueError('Disjoint domain class violation')
        if record['document_id'] != doc['id'] or not record['scope']:
            raise ValueError('Domain record lacks owned document scope')
        if record['class_id'] in {'Building','BuildingPart','BuildingElement','ConstructionSystem','Material','Product','Interface'}:
            if record.get('identification_basis') not in {'explicit_entity_mention','reviewed_entity_resolution'}:
                raise ValueError('Physical entity requires identification evidence; a topic heading is insufficient')
            if record['properties'].get('resolution') == 'reported_heading_candidate':
                raise ValueError('Report heading cannot identify a physical entity')
        if not set(record['anchor_ids']) <= owned or not set(record['block_ids']) <= blocks:
            raise ValueError('Unsupported or foreign domain source')
        if not record['anchor_ids'] and not record['block_ids']:
            structural_assertion = record['class_id']=='QualifiedAssertion' and record['properties'].get('predicate_id') in {'uses_asset','has_gap'}
            if record['asset_hash'] != doc['sha256'] or not (record['class_id'] in {'ReportVersion','OriginalAsset','KnowledgeGap'} or structural_assertion):
                raise ValueError('Domain record has no source evidence')
        fields = set().union(*(set(classes[c]['properties']) for c in lineage))
        if not set(record['properties']) <= fields:
            raise ValueError('Undeclared domain property')
        for key, value in record['properties'].items():
            expected = model['property_types'][key]
            if value is not None and not isinstance(value, {'string_or_unknown': str, 'array_or_unknown': list,
                                                            'integer_or_unknown': int}[expected]):
                raise ValueError('Invalid domain property value')
        for dimension, values in model['status_dimensions'].items():
            if record[dimension] not in values:
                raise ValueError('Invalid independent evidence status')
        if record['class_id'] == 'RepairEvent' and record['repair_outcome'] not in {'reported_undertaken','documented_outcome','outcome_unknown'}:
            raise ValueError('Recommendation cannot establish undertaken repair')
        if record['class_id'] == 'ReviewedRule' and (record['review_state'] != 'reviewed' or record['reference_verification'] != 'original_source_matched'):
            raise ValueError('Original reviewed rule gate required')
    for relation in snapshot['relations']:
        if relation['predicate'] not in predicates or relation['subject_id'] not in records or relation['object_id'] not in records:
            raise ValueError('Ungoverned domain relation or missing endpoint')
        definition = predicates[relation['predicate']]
        subject, obj = records[relation['subject_id']], records[relation['object_id']]
        if not ancestors(model, subject['class_id']).intersection(definition['domains']) or not ancestors(model, obj['class_id']).intersection(definition['ranges']):
            raise ValueError('Domain relation type mismatch: ' + relation['predicate'])
        if not relation['scope'] or not set(relation['anchor_ids']) <= owned or not set(relation['block_ids']) <= blocks:
            raise ValueError('Unsupported domain relation scope')
        if not relation['anchor_ids'] and not relation['block_ids']:
            if relation['asset_hash'] != doc['sha256'] or relation['predicate'] not in {'uses_asset','has_gap'}:
                raise ValueError('Domain relation lacks evidence')
        for dimension, values in model['status_dimensions'].items():
            if relation[dimension] not in values:
                raise ValueError('Invalid relation evidence status')
        if relation['predicate'] in {'uses_definition','definition_from','decision_uses_rule','depiction_of'} and relation['reference_verification'] != 'original_source_matched':
            raise ValueError('Reported/OCR identity cannot establish original verification')
        if relation['predicate'] in {'has_classification_assessment','has_applicability_assessment','assesses_class'} and relation['statement_kind'] in {'reported_reference','source_supported_mapping','ocr_extraction'}:
            raise ValueError('Discovery mapping cannot establish classification or applicability')
        if relation['predicate'] in {'has_classification_assessment','has_applicability_assessment','assesses_class'}:
            if relation['reference_verification'] != 'original_source_matched' or relation['review_state'] != 'reviewed':
                raise ValueError('Classification/applicability requires reviewed original source evidence')


def build_snapshot(store: Store, doc_id: str, ontology: 'Ontology') -> dict:
    """Map authored structure and explicit phrases, without inventing missing domain facts."""
    doc = store.require('SELECT * FROM documents WHERE id=?', (doc_id,))
    blocks = {r['id']: r for r in store.all('SELECT * FROM blocks WHERE document_id=? ORDER BY sequence', (doc_id,))}
    anchors = store.all('SELECT * FROM anchors WHERE document_id=?', (doc_id,))
    by_block: dict[str, list[dict]] = {}
    for anchor in anchors:
        by_block.setdefault(anchor['block_id'], []).append(anchor)
    records: dict[str, dict] = {}
    relations: dict[str, dict] = {}
    defaults = {'statement_kind':'structural_document_membership','review_state':'extracted',
                'source_identification':'source_text','reference_verification':'not_applicable',
                'applicability':'not_assessed','repair_outcome':'not_applicable','certainty':'source_recorded',
                'source_availability':'imported'}

    def supports(block_ids):
        result = []
        for bid in block_ids:
            b = blocks[bid]
            if not b['text'].strip():
                continue
            exact = next((a for a in by_block.get(bid, []) if a['start_cp'] == 0 and a['end_cp'] == len(b['text'])), None)
            if not exact:
                aid = identity('anchor', bid, 0, len(b['text']), digest(b['text']))
                exact = {'id':aid,'block_id':bid,'document_id':doc_id,'start_cp':0,'end_cp':len(b['text']),'quote_hash':digest(b['text'])}
                store.insert('anchors', exact)
                by_block.setdefault(bid, []).append(exact)
            result.append(exact['id'])
        return sorted(set(result))

    def add(rid, cls, label, bids=(), aids=(), properties=None, scope=None, **status):
        support = sorted(set(aids) | set(supports(bids)))
        record = {'id':rid,'class_id':cls,'label':label,'document_id':doc_id,'scope':scope or doc_id,
                  'properties':properties or {},'anchor_ids':support,'block_ids':sorted(set(bids)),
                  'asset_hash':doc['sha256'],**defaults,**status}
        if rid in records:
            previous = records[rid]
            if previous['class_id'] != cls:
                raise ValueError('Conflicting domain record class')
            record['anchor_ids'] = sorted(set(previous['anchor_ids'] + support))
            record['block_ids'] = sorted(set(previous['block_ids'] + record['block_ids']))
        records[rid] = record
        return rid

    def link(subject, predicate, obj, bids=(), aids=(), scope=None, **status):
        rid = identity('domain_assertion', doc_id, subject, predicate, obj, scope or records[subject]['scope'], list(bids), list(aids))
        relations[rid] = {'id':rid,'subject_id':subject,'predicate':predicate,'object_id':obj,
                         'scope':scope or records[subject]['scope'],'anchor_ids':sorted(set(aids) | set(supports(bids))),
                         'block_ids':sorted(set(bids)),'asset_hash':doc['sha256'],**defaults,**status}
        return rid

    add(doc_id,'ReportVersion',doc['filename'],properties={'filename':doc['filename'],'asset_hash':doc['sha256'],
                                                         'document_role':doc['role'],'source_availability':'imported'})
    asset = store.require('SELECT * FROM assets WHERE id=?', (doc['asset_id'],))
    add(asset['id'],'OriginalAsset',doc['filename'],properties={'asset_hash':asset['sha256'],'mime_type':asset['mime'],'byte_size':asset['size']})
    link(doc_id,'uses_asset',asset['id'])
    items = store.all('SELECT * FROM items WHERE document_id=?', (doc_id,))
    for item in items:
        aids = [item['heading_anchor_id']] if item['heading_anchor_id'] else []
        add(item['id'],'DefectItem',item['title'],aids=aids,properties={'recorded_name':item['title']},scope=item['id'])
        link(doc_id,'contains_item',item['id'],aids=aids,scope=item['id'])
        # A report topic is a document grouping. Its title cannot mint a physical element.
    for finding in store.all('SELECT * FROM findings WHERE document_id=?', (doc_id,)):
        aids = [finding['anchor_id']]
        add(finding['id'],'DefectOccurrence',finding['identifier']+' · '+finding['location'],aids=aids,
            properties={'recorded_identifier':finding['identifier'],'recorded_location':finding['location'],
                        'schedule_context':finding['item_id']},scope=finding['id'])
        link(finding['item_id'],'has_occurrence',finding['id'],aids=aids,scope=finding['id'])
        if finding['location']:
            loc = add(identity('location',finding['id']),'Location',finding['location'],aids=aids,
                      properties={'recorded_location':finding['location'],'location_role':'reported_occurrence_location'},scope=finding['id'])
            link(finding['id'],'has_location',loc,aids=aids)
    units = store.all('SELECT u.*,p.text FROM units u JOIN parents p ON p.id=u.parent_id WHERE u.document_id=? AND u.semantic_revision=? ORDER BY u.rowid', (doc_id, doc['active_semantic_revision']))
    unit_blocks = {u['id']:[b['block_id'] for b in store.all('SELECT block_id FROM unit_blocks WHERE unit_id=? ORDER BY sequence',(u['id'],))] for u in units}
    block_units: dict[str, dict] = {}
    for unit in units:
        bids = unit_blocks[unit['id']]
        block_units.update({bid:unit for bid in bids})
        cls = {'observation':'Observation','occurrence_observation':'Observation','reasoning':'Reasoning','extent':'OccurrenceExtentAssessment','status':'StatusAssessment',
               'result':'ConsequenceAssessment','responsibility':'ResponsibilityAssessment','remediation':'RemediationScope','remediation_option':'RemediationScope'}.get(unit['kind'],'LogicalUnit')
        scope = unit['finding_id'] or unit['item_id'] or doc_id
        add(unit['id'],cls,unit['kind'].replace('_',' ').title(),bids,properties={'recorded_text':unit['text']},scope=scope,
            statement_kind='recorded_observation' if cls=='Observation' else 'ocr_extraction' if unit['kind']=='visual_extract' else 'author_opinion',
            review_state='uncertain' if unit['kind']=='visual_extract' else 'extracted',certainty='author_attributed' if cls!='Observation' else 'source_recorded')
        subject = unit['finding_id'] or unit['item_id']
        if subject and cls not in {'RemediationScope','LogicalUnit'}:
            predicate = {'Observation':'records_observation','Reasoning':'has_reasoning','OccurrenceExtentAssessment':'has_extent',
                         'StatusAssessment':'has_status','ConsequenceAssessment':'has_consequence','ResponsibilityAssessment':'has_responsibility'}[cls]
            link(subject,predicate,unit['id'],bids,statement_kind=records[unit['id']]['statement_kind'],scope=scope,certainty=records[unit['id']]['certainty'])
        if unit['item_id']:
            link(unit['item_id'],'contains_unit',unit['id'],bids,scope=scope)
        # Preserve individually authored assertions within shared reasoning; never resolve generic roles to people.
        for bid in bids:
            text = blocks[bid]['text'].strip()
            if not text:
                continue
            role = re.match(r'The (Builder|Architect|Certifier|Waterproofer)\b',text,re.I)
            if role and unit['kind'] in {'reasoning','responsibility'} and subject:
                assessment = add(identity('responsibility',bid),'ResponsibilityAssessment',role[1]+' responsibility opinion',[bid],
                                 properties={'recorded_text':text,'schedule_context':unit['item_id']},scope=scope,
                                 statement_kind='author_opinion',certainty='author_attributed')
                partyrole = add(identity('partyrole',doc_id,role[1].lower()),'PartyRole',role[1],[bid],properties={'role_name':role[1]},
                                statement_kind='source_supported_mapping',certainty='unresolved')
                link(subject,'has_responsibility',assessment,[bid],statement_kind='author_opinion',certainty='author_attributed',scope=scope)
                link(assessment,'assesses_responsibility',partyrole,[bid],statement_kind='author_opinion',certainty='author_attributed')
            if unit['kind']=='reasoning' and re.search(r'\binstructed me\b|\breported (?:that|by)\b',text,re.I) and subject:
                history = add(identity('history',bid),'ReportedHistory','Reported history',[bid],properties={'recorded_text':text},scope=scope,statement_kind='reported_history',certainty='author_attributed')
                link(unit['id'],'has_history',history,[bid],statement_kind='reported_history',certainty='author_attributed',scope=scope)
            if unit['kind']=='reasoning' and re.search(r'\b(?:causes? (?:of|this)|resulted from|due to|caused by|either of the following)\b',text,re.I) and subject:
                uncertain = bool(re.search(r'\b(?:or|either|may|likely|possible|combination)\b',text,re.I))
                cause = add(identity('cause',bid),'CauseAssessment','Attributed cause assessment',[bid],properties={'recorded_text':text,'causal_certainty':'suspected_or_alternative' if uncertain else 'author_attributed'},scope=scope,
                            statement_kind='author_opinion',certainty='suspected_or_alternative' if uncertain else 'author_attributed')
                link(subject,'has_cause_assessment',cause,[bid],statement_kind='author_opinion',certainty=records[cause]['certainty'],scope=scope)
            if unit['kind'] in {'observation','occurrence_observation','reasoning'} and re.search(r'\d\s*(?:mm\b|MPa\b|%|/\s*1000\b)',text,re.I) and subject:
                values = re.findall(r'\d+(?:\.\d+)?\s*(?:mm\b|MPa\b|%|/\s*1000\b)',text,re.I)
                measurement = add(identity('measurement',bid),'TestMeasurement','Recorded reading / dimension',[bid],properties={'recorded_text':text,'value_as_written':'; '.join(values),'units_as_written':None,'instrument':None,'measurement_date':None},scope=scope,
                                  statement_kind=records[unit['id']]['statement_kind'],certainty='unresolved')
                link(subject,'has_measurement',measurement,[bid],statement_kind=records[unit['id']]['statement_kind'],certainty='unresolved',scope=scope)
            if unit['kind']=='reasoning' and re.search(r'(?:not been (?:provided|supplied)|not provided|unavailable|missing (?:document|attachment))',text,re.I):
                gap = add(identity('gap',bid),'KnowledgeGap','Source not supplied',[bid],properties={'gap_kind':'source_not_supplied','recorded_text':text,'source_availability':'not_supplied'},scope=scope,statement_kind='author_opinion',certainty='author_attributed',source_availability='not_supplied')
                link(unit['id'],'has_gap',gap,[bid],statement_kind='author_opinion',certainty='author_attributed',source_availability='not_supplied')
            if unit['kind']=='reasoning' and re.search(r'\b(?:Occupation Certificate|Construction Certificate|approved plans|certification)\b',text,re.I):
                approval = add(identity('approval',bid),'ApprovalRecord','Reported approval / certification evidence',[bid],properties={'approval_kind':'reported_approval_reference','recorded_text':text,'recorded_identifier':None,'approval_date':None},scope=scope,
                               statement_kind='reported_reference',reference_verification='reported_only',source_availability='not_supplied',certainty='unresolved')
                link(doc_id,'has_approval_evidence',approval,[bid],scope=scope,statement_kind='reported_reference',reference_verification='reported_only',source_availability='not_supplied',certainty='unresolved')
            if unit['kind']=='reasoning' and subject:
                requirements = []
                for match in re.finditer(r'\b(?:Performance Requirements?\s+([A-Z]{1,3}\d+(?:\s*\.\s*\d+)+)|(?:DTS|Deemed[- ]to[- ]Satisfy)\s+(?:provisions?|clauses?)\s+([A-Z]\d+(?:\.\d+)*))',text,re.I):
                    cid = 'PerformanceRequirement' if match[1] else 'DTSProvision'
                    requirement = add(identity('requirement_mention',bid,match[0]),cid,match[0],[bid],properties={'recorded_text':text,'requirement_identifier':match[1] or match[2]},scope=scope,
                                      statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved',certainty='author_attributed',source_availability='not_supplied')
                    requirements.append(requirement)
                    link(unit['id'],'considers_requirement',requirement,[bid],statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved',certainty='author_attributed')
                if re.search(r'\b(?:non[- ]compliance|not (?:being )?compliant|breach of|does not comply|not meet)\b',text,re.I):
                    compliance = add(identity('compliance_opinion',bid),'ComplianceAssessment','Authored compliance opinion',[bid],properties={'recorded_text':text},scope=scope,statement_kind='author_opinion',certainty='author_attributed',applicability='unresolved')
                    link(subject,'has_assessment',compliance,[bid],statement_kind='author_opinion',certainty='author_attributed',scope=scope,applicability='unresolved')
                    for requirement in requirements:
                        link(compliance,'considers_requirement',requirement,[bid],statement_kind='author_opinion',certainty='author_attributed',reference_verification='reported_only',applicability='unresolved')
    # Split source-introduced alternatives even when numbered options occur inside prose.
    option_groups: dict[str, list[str]] = {}
    for original in store.all('SELECT o.*,i.title AS item_title FROM options o JOIN items i ON i.id=o.item_id WHERE i.document_id=?',(doc_id,)):
        selected = [u for u in units if u['option_id']==original['id'] and u['kind'] in {'remediation','remediation_option'}]
        all_bids = list(dict.fromkeys(b for u in selected for b in unit_blocks[u['id']]))
        segments = option_segments([(bid,blocks[bid]['text']) for bid in all_bids])
        for number,bids in segments:
            substantive = [b for b in bids if len(blocks[b]['text'].strip())>15 and not re.fullmatch(r'(?:remediation|option\s*\d+)\s*[:.]?',blocks[b]['text'].strip(),re.I)]
            if not substantive:
                continue
            split = len(segments)>1
            option_id = identity('source_option',original['id'],number,bids[0]) if split else original['id']
            title = 'Option '+number if number else original['title'].strip()
            group = original['item_id'] if number or re.match(r'Option\s*\d+',title,re.I) else None
            text = '\n'.join(blocks[b]['text'] for b in bids if blocks[b]['text'].strip())
            label = original['item_title']+' · '+title
            limitations = '\n'.join(blocks[b]['text'] for b in bids if re.search(r'\b(?:depending|subject to|may require|wider|entire bathroom|only where)\b',blocks[b]['text'],re.I)) or None
            add(option_id,'RemediationOption',label,bids,properties={'recorded_name':title,'work_scope':text,'alternative_group':group,'limitations':limitations},scope=original['item_id'],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            link(original['item_id'],'has_remediation',option_id,bids,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            if group:
                option_groups.setdefault(group,[]).append(option_id)
            if split:
                scope_id = add(identity('option_scope',option_id),'RemediationScope',label+' scope',bids,properties={'recorded_text':text,'limitations':limitations},scope=option_id,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                link(option_id,'option_scope',scope_id,bids,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            else:
                for unit in selected:
                    link(option_id,'option_scope',unit['id'],unit_blocks[unit['id']],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            work_id = add(identity('proposed_work',option_id),'ProposedRemedialWork',label+' proposed work',bids,properties={'work_scope':text},scope=option_id,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            link(option_id,'proposes_work',work_id,bids,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
            for sequence,bid in enumerate(substantive,1):
                text = blocks[bid]['text'].strip()
                if option_number(text):
                    continue
                step = add(identity('step',option_id,bid),'RemediationStep','Proposed step '+str(sequence),[bid],properties={'sequence':sequence,'recorded_text':text},scope=option_id,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                link(option_id,'has_step',step,[bid],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                if re.search(r'\b(?:obtain|before|approval|design|consent|access|accommodation)\b',text,re.I):
                    prereq = add(identity('prerequisite',option_id,bid),'Prerequisite','Source-stated prerequisite',[bid],properties={'recorded_text':text,'prerequisite_kind':'source_stated_condition'},scope=option_id,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                    link(option_id,'has_prerequisite',prereq,[bid],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                if re.search(r'\b(?:verify|verification|acceptance|test(?:ing)? (?:to|for|of)|ensure.+(?:ventilation|required|compliance))\b',text,re.I):
                    criterion = add(identity('criterion',option_id,bid),'VerificationCriterion','Proposed verification criterion',[bid],properties={'recorded_text':text},scope=option_id,statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
                    link(option_id,'has_verification_criterion',criterion,[bid],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
    for group in option_groups.values():
        for left,right in zip(group,group[1:],strict=False):
            link(left,'alternative_to',right,aids=records[left]['anchor_ids']+records[right]['anchor_ids'],statement_kind='author_opinion',repair_outcome='recommended',certainty='author_attributed')
    for work in store.all('SELECT w.* FROM work_events w JOIN items i ON i.id=w.item_id WHERE i.document_id=?',(doc_id,)):
        payload = json.loads(work['payload'])
        add(work['id'],'RepairEvent','Reported previous repair',[ ],[work['anchor_id']],properties={'work_kind':work['kind'],'recorded_outcome':payload.get('outcome'),'work_date':payload.get('date'),'work_scope':payload.get('text')},scope=work['item_id'],statement_kind='reported_history',repair_outcome='reported_undertaken',certainty='author_attributed')
        link(work['item_id'],'records_repair',work['id'],aids=[work['anchor_id']],statement_kind='reported_history',repair_outcome='reported_undertaken',certainty='author_attributed')
    # Edition identity comes only from the literal citation, never from a date-based adoption heuristic.
    for ref in store.all('SELECT * FROM references_catalog WHERE document_id=?',(doc_id,)):
        value = json.loads(ref['identity_json'])
        aids = [ref['anchor_id']]
        family = value.get('family') or ref['label']
        is_as = family.startswith('AS ')
        fid = add(identity('reference_family',doc_id,family),'StandardFamily' if is_as else 'CodeFamily',family,aids=aids,properties={'reference_family':family},statement_kind='reported_reference',reference_verification='reported_only')
        target = fid
        if is_as and value.get('part'):
            target = add(identity('standard_part',doc_id,family,value['part']),'StandardPart',family+'.'+value['part'],aids=aids,properties={'reference_family':family,'part_identifier':value['part']},statement_kind='reported_reference',reference_verification='reported_only')
            link(fid,'has_standard_part',target,aids=aids,statement_kind='reported_reference',reference_verification='reported_only')
        if value.get('year'):
            eid = add(identity('reference_edition',doc_id,family,value.get('part'),value['year'],value.get('amendments')),'StandardEdition' if is_as else 'CodeEdition',ref['label'],aids=aids,
                      properties={'reference_family':family,'edition_year':str(value['year']),'amendments':value.get('amendments'),**({'part_identifier':value.get('part')} if is_as else {})},statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
            link(target,'has_edition',eid,aids=aids,statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
            target = eid
        if target != fid or is_as:
            anchor = store.require('SELECT block_id FROM anchors WHERE id=?',(ref['anchor_id'],))
            cited_unit = block_units.get(anchor['block_id'])
            subject = cited_unit['id'] if cited_unit and (records[cited_unit['id']]['class_id']=='Reasoning' or 'Assessment' in ancestors(ontology.domain_model,records[cited_unit['id']]['class_id'])) else cited_unit['item_id'] if cited_unit and cited_unit['item_id'] else doc_id
            link(subject,'cites_edition',target,aids=aids,statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
            if cited_unit and cited_unit['kind']=='reasoning' and records[target]['class_id'] in {'StandardEdition','CodeEdition'}:
                relationship = add(ref['id'],'ReferenceRelationship','Reported citation: '+ref['label'],aids=aids,
                                   properties={'reference_basis':'report_cited','conditions':None,'exceptions':None,'recorded_text':blocks[anchor['block_id']]['text']},scope=records[cited_unit['id']]['scope'],
                                   statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
                link(cited_unit['id'],'has_reference_relationship',relationship,aids=aids,statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
                link(relationship,'references_source',target,aids=aids,statement_kind='reported_reference',reference_verification='reported_only',applicability='unresolved')
    for media in store.all('SELECT * FROM media WHERE document_id=?',(doc_id,)):
        bid = media['block_id']
        metadata = json.loads(media['identity_json'])
        add(media['id'],'ImageOccurrence',media['caption'] or 'Image occurrence',[bid],properties={'caption':media['caption'],'image_role':media['role'],'source_locator':blocks[bid]['locator']},source_identification='caption_candidate' if media['caption'] else 'unknown',certainty='unresolved')
        image = store.require('SELECT * FROM assets WHERE id=?',(media['asset_id'],))
        add(image['id'],'ImageAsset','Original image',[bid],properties={'asset_hash':image['sha256'],'mime_type':image['mime'],'byte_size':image['size']})
        link(doc_id,'has_image_occurrence',media['id'],[bid])
        link(media['id'],'uses_asset',image['id'],[bid])
        for iid in {u['item_id'] for u in units if u['item_id'] and bid in unit_blocks[u['id']]}:
            link(iid,'has_visual_context',media['id'],[bid],scope=iid)
        for visual in store.all('SELECT * FROM visuals WHERE media_id=?',(media['id'],)):
            add(visual['id'],'OCRExtraction','OCR extraction',[bid],properties={'recorded_text':visual['text'],'extraction_method':visual['method'],'regions':json.loads(visual['regions']),'reading_order':None},statement_kind='ocr_extraction',review_state='uncertain',source_identification='ocr_candidate',certainty='unresolved')
            link(media['id'],'has_ocr',visual['id'],[bid],statement_kind='ocr_extraction',review_state='uncertain',source_identification='ocr_candidate',certainty='unresolved')
        for index, fragment in enumerate(metadata.get('fragments',[])):
            fragment = fragment if isinstance(fragment,dict) else {'identifier':str(fragment)}
            depicted = add(identity('depicted',media['id'],index,fragment),'DepictedFragment',str(fragment.get('kind','Fragment'))+' '+str(fragment.get('identifier') or fragment.get('number') or fragment.get('label') or '?'),[bid],
                           properties={'fragment_kind':str(fragment.get('kind') or 'unknown'),'fragment_identifier':str(fragment.get('identifier') or fragment.get('number') or fragment.get('label') or ''),'printed_source_page':str(metadata['source_printed_page']) if metadata.get('source_printed_page') else None},
                           statement_kind='ocr_extraction',review_state='uncertain',source_identification='ocr_candidate',reference_verification='embedded_extract_identified',applicability='unresolved',certainty='unresolved')
            link(media['id'],'depicts_fragment',depicted,[bid],statement_kind='ocr_extraction',review_state='uncertain',source_identification='ocr_candidate',reference_verification='embedded_extract_identified',applicability='unresolved',certainty='unresolved')
    for anchor in store.all('SELECT * FROM anchors WHERE document_id=?',(doc_id,)):
        block = blocks[anchor['block_id']]
        add(anchor['id'],'TextPassage','Source passage',aids=[anchor['id']],properties={'recorded_text':block['text'][anchor['start_cp']:anchor['end_cp']],'start_cp':anchor['start_cp'],'end_cp':anchor['end_cp'],'content_kind':block['content_kind'],'source_locator':block['locator']},statement_kind='ocr_extraction' if block['content_kind']=='visual_extract' else 'structural_document_membership')
    for assertion in store.all('SELECT * FROM assertions WHERE document_id=?',(doc_id,)):
        aids = [r['anchor_id'] for r in store.all('SELECT anchor_id FROM assertion_support WHERE assertion_id=?',(assertion['id'],))]
        add(assertion['id'],'QualifiedAssertion',assertion['predicate'].replace('_',' '),aids=aids,properties={'predicate_id':assertion['predicate'],'subject_id':assertion['subject_id'],'object_id':assertion['object_id']},scope=assertion['scope'],statement_kind=assertion['kind'])
    for chunk in store.all('SELECT c.*,ch.unit_id FROM chunk_revisions c JOIN chunks ch ON ch.id=c.chunk_id JOIN units u ON u.id=ch.unit_id WHERE c.document_id=? AND u.semantic_revision=? AND c.rowid IN (SELECT MAX(rowid) FROM chunk_revisions GROUP BY chunk_id)',(doc_id,doc['active_semantic_revision'])):
        chunk_spans = store.all('SELECT * FROM chunk_segments WHERE revision_id=? ORDER BY sequence',(chunk['id'],))
        bids = [s['block_id'] for s in chunk_spans]
        add(chunk['id'],'EvidenceChunk',chunk['header'],bids,properties={'content_kind':json.loads(chunk['metadata'])['content_kind'],'source_segments':chunk_spans},scope=records[chunk['unit_id']]['scope'])
        link(chunk['unit_id'],'has_evidence_chunk',chunk['id'],bids)
    for review in store.all("SELECT * FROM reviews WHERE document_id=? AND state='needs_review'",(doc_id,)):
        aids = json.loads(review['anchor_ids'])
        gap = add(identity('domain_gap',review['id']),'KnowledgeGap',review['kind'].replace('_',' '),aids=aids,properties={'gap_kind':review['kind'],'recorded_text':review['message'],'source_availability':'unresolved'},review_state='uncertain',certainty='unresolved')
        link(doc_id,'has_gap',gap,aids=aids,review_state='uncertain',certainty='unresolved')
    for relation in relations.values():
        add(relation['id'],'QualifiedAssertion',relation['predicate'].replace('_',' '),relation['block_ids'],relation['anchor_ids'],
            properties={'predicate_id':relation['predicate'],'subject_id':relation['subject_id'],'object_id':relation['object_id']},
            scope=relation['scope'],**{key:relation[key] for key in defaults})
    snapshot = {'document_id':doc_id,'ontology_version':ontology.domain_version,'source_semantic':doc['active_semantic_revision'],
                'extraction_method':'document_evidence_mapping/2','interpretation_status':'unreviewed',
                'records':sorted(records.values(),key=lambda r:r['id']),
                'relations':sorted(relations.values(),key=lambda r:r['id'])}
    validate_snapshot(store,snapshot,ontology.domain_model)
    snapshot['id'] = identity('domain_snapshot',snapshot)
    store.insert('domain_snapshots',{'id':snapshot['id'],'document_id':doc_id,'ontology_version':ontology.domain_version,
                                   'source_semantic':doc['active_semantic_revision'] or '', 'payload':snapshot,'created':time.time()})
    return snapshot


def graph_batch(snapshot: dict, model: dict) -> dict:
    nodes = [{'id':r['id'],'kind':r['class_id'],'label':r['label'],'payload':r} for r in snapshot['records']]
    records = {r['id']:r for r in snapshot['records']}
    edges = []
    for relation in snapshot['relations']:
        nodes.append({'id':relation['id'],'kind':'DomainAssertion','label':relation['predicate'].replace('_',' '),
                      'payload':{**relation,'domain':records[relation['id']],'domain_class':'QualifiedAssertion',
                                 'kind':relation['statement_kind'],'state':relation['review_state'],
                                 'value':None,'snapshot_id':snapshot['id']}})
        # Direct, qualified links make the domain graph navigable without losing reified provenance.
        edges.append({'source':relation['subject_id'],'target':relation['object_id'],'kind':relation['predicate'], 'assertion_id':relation['id']})
        edges += [{'source':relation['id'],'target':relation[key],'kind':label,'assertion_id':relation['id']} for key,label in [('subject_id','HAS_SUBJECT'),('object_id','HAS_OBJECT')]]
        edges += [{'source':relation['id'],'target':aid,'kind':'SUPPORTED_BY','assertion_id':relation['id']} for aid in relation['anchor_ids']]
    for cls in model['classes']:
        nodes.append({'id':'schema:'+cls['id'],'kind':'OntologyClass','label':cls['label'],'payload':cls})
        if cls['parent']:
            edges.append({'source':'schema:'+cls['id'],'target':'schema:'+cls['parent'],'kind':'SUBCLASS_OF','assertion_id':'schema:'+snapshot['ontology_version']})
    edges += [{'source':r['id'],'target':'schema:'+r['class_id'],'kind':'INSTANCE_OF','assertion_id':'schema:'+snapshot['ontology_version']} for r in snapshot['records']]
    return {'nodes':list({n['id']:n for n in nodes}.values()),'edges':edges}


def published_snapshots(store: Store, manifest_id: str | None = None) -> list[dict]:
    return [json.loads(r['payload']) for r in store.all(
        "SELECT ds.payload FROM domain_snapshots ds JOIN projections p ON ds.id=json_extract(p.receipts,'$.domain.snapshot_id') "
        "JOIN manifest_members mm ON mm.projection_id=p.id WHERE mm.manifest_id=? ORDER BY ds.document_id", (manifest_id or store.active_manifest(),))]


def instance_catalog(store: Store, model: dict, class_id: str, query='', limit=50, offset=0):
    descendants = {c['id'] for c in model['classes'] if class_id in ancestors(model,c['id'])}
    if not descendants:
        raise KeyError('Unknown domain class')
    rows = [r for snapshot in published_snapshots(store) for r in snapshot['records'] if r['class_id'] in descendants]
    if query:
        rows = [r for r in rows if query.lower() in (r['label']+' '+json.dumps(r['properties'],ensure_ascii=False)).lower()]
    rows.sort(key=lambda r:(r['class_id'],r['label'],r['id']))
    return {'items':rows[offset:offset+limit],'total':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None,'manifest_id':store.active_manifest()}


def usage(store: Store, model: dict) -> dict:
    snapshots = published_snapshots(store)
    counts = Counter(r['class_id'] for snapshot in snapshots for r in snapshot['records'])
    return {'class_counts':dict(counts),'populated_classes':len(counts),'records':sum(counts.values()),
            'relationships':sum(len(s['relations']) for s in snapshots),'documents':len(snapshots),
            'snapshots':[{'id':s['id'],'document_id':s['document_id'],'ontology_version':s['ontology_version']} for s in snapshots],
            'manifest_id':store.active_manifest()}


def scope_label(store: Store, scope: str) -> str:
    row = store.one('SELECT title AS label FROM items WHERE id=? UNION ALL SELECT identifier || \' · \' || location FROM findings WHERE id=? UNION ALL SELECT filename FROM documents WHERE id=? LIMIT 1',(scope,scope,scope))
    return row['label'] if row else scope.replace('_',' ')
