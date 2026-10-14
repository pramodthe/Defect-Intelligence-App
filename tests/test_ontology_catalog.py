from app.ontology import Ontology
from tests.conftest import publish_fixture


def test_catalog_usage_only_counts_active_publication(store, ontology):
    empty_manifest = store.active_manifest()
    publish_fixture(store, ontology)
    catalog = ontology.public_catalog()
    assert any(c['evidence_chunks'] > 0 for c in catalog['items'])
    assert {e['label'] for e in catalog['edges']} == {'type'}
    ids = {n['id'] for n in catalog['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in catalog['edges'])
    store.execute("UPDATE workspace SET value=? WHERE key='manifest'", (empty_manifest,))
    assert all(c['evidence_chunks'] == 0 for c in Ontology(store).public_catalog()['items'])


def test_ontology_keeps_class_senses_separate(store, ontology):
    matches = ontology.resolve('Class 2', 'Class 2')
    assert {c['family'] for c in matches} == {'BuildingClass', 'ConcreteFinishClass', 'MembraneClass'}
    catalog = ontology.public_catalog()
    assert {'classified_as', 'references', 'supported_by'} <= set(catalog['allowed_predicates'])
    assert all(c['evidence_chunks'] == 0 for c in catalog['items'])
