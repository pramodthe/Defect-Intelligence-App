import copy
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import OWL, RDFS, RDF, SKOS
from io import BytesIO
from docx import Document

from app.domain import ancestors, build_snapshot, instance_catalog, published_snapshots, validate_snapshot, option_segments
from app.ontology import MODEL_PATH
from tests.conftest import publish_fixture, synthetic_docx


def test_full_schema_tracks_specification_and_typed_hierarchy(ontology):
    model = ontology.domain_model
    spec = MODEL_PATH.parents[2] / 'ONTOLOGY.md'
    headings = [line[3:].strip() for line in spec.read_text('utf-8').splitlines() if line.startswith('## ')]
    assert {c['section'] for c in model['source_coverage']} == set(headings)
    assert all(c['covered_by'] for c in model['source_coverage'])
    assert model['source_sha256'] == hashlib.sha256(spec.read_bytes()).hexdigest()
    assert len(model['classes']) == 99 and len(model['relationships']) == 86
    ids = {c['id'] for c in model['classes']}
    for cls in model['classes']:
        assert 'DomainRecord' in ancestors(model,cls['id'])
    for relation in model['relationships']:
        assert set(relation['domains']+relation['ranges']) <= ids
        assert relation['requires_source'] and relation['requires_scope']
    assert (ontology.ns.BuildingClass,OWL.disjointWith,ontology.ns.ConcreteFinishClass) in ontology.rdf
    assert (ontology.ns.ResponsibilityAssessment,RDFS.subClassOf,ontology.ns.ExpertAssessment) in ontology.rdf
    # Multiple legal domain alternatives are an OWL union, not an RDFS intersection.
    domain = ontology.rdf.value(ontology.ns['relation:has_measurement'],RDFS.domain)
    assert ontology.rdf.value(domain,OWL.unionOf) is not None


def test_domain_instances_preserve_alternatives_reused_images_and_reported_editions(store,ontology):
    result = publish_fixture(store,ontology)
    snapshot = published_snapshots(store)[0]
    assert build_snapshot(store,result['document_id'],ontology)['id'] == snapshot['id']
    records = snapshot['records']
    assert len([r for r in records if r['class_id']=='DefectOccurrence']) == 3
    options = [r for r in records if r['class_id']=='RemediationOption']
    assert len(options) == 2
    assert all(r['repair_outcome']=='recommended' for r in options)
    assert not any(r['class_id']=='RepairEvent' for r in records)
    assert any(r['predicate']=='alternative_to' for r in snapshot['relations'])
    assert len([r for r in records if r['class_id']=='ImageOccurrence']) == 2
    assert len([r for r in records if r['class_id']=='ImageAsset']) == 1
    editions = [r for r in records if r['class_id'] in {'CodeEdition','StandardEdition'}]
    assert editions and all(r['reference_verification']=='reported_only' for r in editions)
    assert {'2016','2022'} <= {r['properties']['edition_year'] for r in editions}
    assert any(r['class_id']=='TestMeasurement' and '12 mm' in r['properties']['recorded_text'] for r in records)
    assert not any(r['applicability']=='supported' for r in records)


def test_snapshot_publication_hides_staged_and_old_records(store,ontology):
    empty = store.active_manifest()
    publish_fixture(store,ontology)
    assert instance_catalog(store,ontology.domain_model,'DomainRecord')['total'] > 0
    store.execute("UPDATE workspace SET value=? WHERE key='manifest'",(empty,))
    assert not published_snapshots(store)
    assert instance_catalog(store,ontology.domain_model,'DefectOccurrence')['total'] == 0
    with pytest.raises(KeyError):
        instance_catalog(store,ontology.domain_model,'MadeUpClass')


def test_snapshot_rejects_foreign_sources_invalid_types_and_invented_repairs(store,ontology):
    publish_fixture(store,ontology)
    original = published_snapshots(store)[0]
    bad = copy.deepcopy(original)
    bad['records'][0]['anchor_ids'] = ['anchor_from_another_report']
    with pytest.raises(ValueError,match='foreign domain source'):
        validate_snapshot(store,bad,ontology.domain_model)
    bad = copy.deepcopy(original)
    relation = next(r for r in bad['relations'] if r['predicate']=='has_occurrence')
    relation['predicate'] = 'uses_product'
    with pytest.raises(ValueError,match='type mismatch'):
        validate_snapshot(store,bad,ontology.domain_model)
    bad = copy.deepcopy(original)
    record = next(r for r in bad['records'] if r['class_id']=='RemediationOption')
    record['class_id'] = 'RepairEvent'
    record['properties'] = {}
    with pytest.raises(ValueError,match='undertaken repair'):
        validate_snapshot(store,bad,ontology.domain_model)
    bad = copy.deepcopy(original)
    record = next(r for r in bad['records'] if r['class_id']=='Observation')
    record['anchor_ids'] = []
    record['block_ids'] = []
    with pytest.raises(ValueError,match='no source evidence'):
        validate_snapshot(store,bad,ontology.domain_model)


def test_report_or_ocr_cannot_create_original_verified_relationship(store,ontology):
    publish_fixture(store,ontology)
    bad = copy.deepcopy(published_snapshots(store)[0])
    source = next(r for r in bad['records'] if r['class_id']=='RemediationOption')
    target = next(r for r in bad['records'] if r['class_id']=='RemediationScope')
    source['class_id'] = 'ClassificationDefinition'
    target['class_id'] = 'SourceFragment'
    source['properties'] = target['properties'] = {}
    # Test the original-source gate in isolation, after retaining only this relation.
    base = next(r for r in bad['relations'] if r['predicate']=='option_scope')
    bad['relations'] = [{**base,'predicate':'definition_from','subject_id':source['id'],'object_id':target['id'],
                         'statement_kind':'ocr_extraction','reference_verification':'embedded_extract_identified'}]
    with pytest.raises(ValueError,match='original verification'):
        validate_snapshot(store,bad,ontology.domain_model)


def test_domain_json_is_a_governed_catalog_not_a_ttl_side_effect():
    model = json.loads(MODEL_PATH.read_text('utf-8'))
    assert 'no_recommendation_implementation' in {c['id'] for c in model['constraints']}
    assert not list(Path(MODEL_PATH.parent).glob('*.ttl'))


def test_prose_alternatives_preserve_separate_scopes_and_references():
    blocks = [('heading','Remediation:'),('one','The remediation scope includes the below as Option 1, closing the corridor walls:'),
              ('design','Obtain approval before enclosing the ends.'),('two','Alternatively, Option 2 would require:'),
              ('waterproof','Waterproof the corridor. Do not combine with Option 1.')]
    assert option_segments(blocks) == [('1',['one','design']),('2',['two','waterproof'])]
    assert option_segments([('ponding','Remediation - Ponding'),('work','Replace screed')]) == [(None,['ponding','work'])]


def test_importing_different_reports_does_not_modify_shared_schema(store,ontology):
    before=copy.deepcopy(ontology.public_schema())
    schema_bytes=MODEL_PATH.read_bytes()
    first=publish_fixture(store,ontology)
    doc=Document(BytesIO(synthetic_docx(count=4)))
    for paragraph in doc.paragraphs:
        paragraph.text=paragraph.text.replace('Planter Box Membrane','Corrosion and staining').replace('Unit','Different building level')
    raw=BytesIO()
    doc.save(raw)
    second=publish_fixture(store,ontology,raw.getvalue())
    assert first['document_id']!=second['document_id']
    assert ontology.public_schema()==before
    assert MODEL_PATH.read_bytes()==schema_bytes
    assert not {'report','search_vocabulary','items'} & before.keys()
    assert all('instance_count' not in c for c in before['classes'])
    assert not any('DS-' in c['id'] or 'DS-' in c['label'] for c in before['classes'])
    occurrences=instance_catalog(store,ontology.domain_model,'DefectOccurrence',limit=100)['items']
    repeated=[r for r in occurrences if r['properties']['recorded_identifier']=='DS-1']
    assert len(repeated)==2 and len({r['id'] for r in repeated})==2
    assert len({r['document_id'] for r in repeated})==2
    assert not instance_catalog(store,ontology.domain_model,'BuildingElement')['items']


def test_search_words_are_not_physical_objects_or_ontology_classes(ontology):
    assert list(ontology.vocabulary_rdf.subjects(RDF.type,SKOS.Concept))
    assert not list(ontology.vocabulary_rdf.subjects(RDF.type,ontology.ns.BuildingElement))
    assert not list(ontology.vocabulary_rdf.subjects(RDF.type,OWL.Class))
    assert not list(ontology.rdf.subjects(RDF.type,SKOS.Concept))
    assert ontology.exact_alias('planter')==['element.planter']


def test_heading_cannot_become_a_physical_element(store,ontology):
    publish_fixture(store,ontology)
    snapshot=copy.deepcopy(published_snapshots(store)[0])
    item=next(r for r in snapshot['records'] if r['class_id']=='DefectItem')
    item['class_id']='BuildingElement'
    item['properties']={'recorded_name':'Corrosion','resolution':'reported_heading_candidate'}
    with pytest.raises(ValueError,match='Physical entity requires identification evidence'):
        validate_snapshot(store,snapshot,ontology.domain_model)
