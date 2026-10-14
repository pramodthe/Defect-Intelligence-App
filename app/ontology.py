import json
import re
from pathlib import Path
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, SKOS, BNode
from rdflib.collection import Collection
from rdflib.term import Node
from app.store import Store, digest

CATALOG_PATH = Path(__file__).resolve().parents[1] / "knowledge/catalog/domain-v1.json"
MODEL_PATH = CATALOG_PATH.with_name('domain-model-v1.json')


class Ontology:
    def __init__(self, store: Store):
        self.store = store
        catalog = json.loads(CATALOG_PATH.read_text("utf-8"))
        self.version = catalog["version"] + ":" + digest(catalog)[:12]
        self.predicates = set(catalog["allowed_predicates"])
        self.definition_status = catalog['definition_status']
        self.concepts = catalog["concepts"]
        self.rdf = Graph()
        self.ns = Namespace("urn:defect-intelligence:")
        self.vocabulary_rdf = Graph()
        self.terms_ns = Namespace('urn:defect-intelligence:search:')
        scheme = self.terms_ns.scheme
        self.vocabulary_rdf.add((scheme,RDF.type,SKOS.ConceptScheme))
        self.domain_model = json.loads(MODEL_PATH.read_text('utf-8'))
        self.domain_version = self.domain_model['version'] + ':' + digest(self.domain_model)[:12]
        for cls in self.domain_model['classes']:
            node = self.ns[cls['id']]
            self.rdf.add((node,RDF.type,OWL.Class))
            self.rdf.add((node,RDFS.label,Literal(cls['label'])))
            self.rdf.add((node,RDFS.comment,Literal(cls['definition'])))
            if cls['parent']:
                self.rdf.add((node,RDFS.subClassOf,self.ns[cls['parent']]))
        for relation in self.domain_model['relationships']:
            node = self.ns['relation:'+relation['id']]
            self.rdf.add((node,RDF.type,OWL.ObjectProperty))
            self.rdf.add((node,RDFS.comment,Literal(relation['definition'])))
            for key,predicate in [('domains',RDFS.domain),('ranges',RDFS.range)]:
                alternatives: list[Node] = [self.ns[c] for c in relation[key]]
                target: Node = alternatives[0]
                if len(alternatives)>1:
                    target = BNode()
                    head = BNode()
                    self.rdf.add((target,RDF.type,OWL.Class))
                    self.rdf.add((target,OWL.unionOf,head))
                    Collection(self.rdf,head,alternatives)
                self.rdf.add((node,predicate,target))
        for group in self.domain_model['disjoint_sets']:
            for i,left in enumerate(group):
                for right in group[i+1:]:
                    self.rdf.add((self.ns[left],OWL.disjointWith,self.ns[right]))
        for c in self.concepts:
            self.store.insert("concepts", {"id": c["id"], "family": c["family"], "label": c["label"],
                "definition": c["definition"], "aliases": c["aliases"], "catalog_version": self.version,
                "payload": {"definition_status": catalog["definition_status"], "source": "ONTOLOGY.md"}})
            term = self.terms_ns[c['id']]
            self.vocabulary_rdf.add((term,RDF.type,SKOS.Concept))
            self.vocabulary_rdf.add((term,SKOS.inScheme,scheme))
            self.vocabulary_rdf.add((term,SKOS.prefLabel,Literal(c['label'])))
            self.vocabulary_rdf.add((term,SKOS.definition,Literal(c['definition'])))
            for alias in c["aliases"]:
                self.vocabulary_rdf.add((term,SKOS.altLabel,Literal(alias.lower())))

    def resolve(self, text: str, context: str = "") -> list[dict]:
        found = []
        for c in self.concepts:
            spans: list[tuple[int, int]] = []
            for alias in c["aliases"]:
                spans.extend((m.start(), m.end()) for m in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I))
            if not spans:
                continue
            if c["family"].endswith("Class"):
                selected_spans = []
                for start,end in spans:
                    before,after = text[max(0,start-50):start].lower(),text[end:end+30].lower()
                    family = None
                    if re.search(r"building\s*$",before) or re.match(r"\s*(?:residential|building)\b",after):
                        family = "BuildingClass"
                    elif re.search(r"finish\s*$",before):
                        family = "ConcreteFinishClass"
                    elif re.search(r"membrane\s*$",before) or re.match(r"\s*membrane\b",after):
                        family = "MembraneClass"
                    else:
                        scope = context.lower()
                        if re.search(r"finish|as\s*3610",scope):
                            family = "ConcreteFinishClass"
                        elif "membrane class" in scope:
                            family = "MembraneClass"
                    if family is None or family == c["family"]:
                        selected_spans.append((start,end))
                spans = selected_spans
                if not spans:
                    continue
            found.append({**c, "spans": sorted(set(spans)), "catalog_version": self.version,
                          "ambiguity": "candidate" if c["family"].endswith("Class") else "mapped"})
        return found

    def exact_alias(self, alias: str):
        # Curated query; caller controls a bound literal, never query syntax.
        result = self.vocabulary_rdf.query("SELECT ?concept WHERE { ?concept <http://www.w3.org/2004/02/skos/core#altLabel> ?alias }",
                                initBindings={"alias": Literal(alias.lower())})
        return [str(r[0]).replace(str(self.terms_ns), "") for r in result if not isinstance(r, bool)]

    def public_catalog(self):
        """Expose actual concept types and their use within the active publication only."""
        counts = {r['concept_id']: r['count'] for r in self.store.all(
            "SELECT cl.concept_id,COUNT(DISTINCT cl.revision_id) AS count FROM chunk_links cl "
            "JOIN projections p JOIN manifest_members mm ON mm.projection_id=p.id "
            "JOIN json_each(p.chunk_ids) ids ON ids.value=cl.revision_id WHERE mm.manifest_id=? GROUP BY cl.concept_id",
            (self.store.active_manifest(),))}
        families = sorted({c['family'] for c in self.concepts})
        items = [{**c, 'evidence_chunks': counts.get(c['id'], 0)} for c in self.concepts]
        nodes = [{'id': 'family:' + family, 'label': family, 'kind': 'ConceptFamily'} for family in families]
        nodes += [{'id': c['id'], 'label': c['label'], 'kind': 'Concept', 'family': c['family']} for c in items]
        edges = [{'id': 'type:' + c['id'], 'source': c['id'], 'target': 'family:' + c['family'],
                  'label': 'type'} for c in items]
        return {'items': items, 'version': self.version, 'definition_status': self.definition_status,
                'allowed_predicates': sorted(self.predicates), 'families': families, 'nodes': nodes, 'edges': edges,
                'manifest_id': self.store.active_manifest()}

    def public_model(self):
        from app.domain import usage
        report = usage(self.store,self.domain_model)
        classes = [{**c,'instance_count':report['class_counts'].get(c['id'],0)} for c in self.domain_model['classes']]
        return {**self.domain_model,'classes':classes,'version':self.domain_version,
                'groups':sorted({c['group'] for c in classes}),'report':report,
                'search_vocabulary':self.public_catalog()}

    def public_schema(self):
        """Report-independent definitions only. No instances, identifiers, counts or search words."""
        return {**self.domain_model,'version':self.domain_version,
                'namespace':str(self.ns),'scope':'shared_across_reports','validation_status':'draft_requires_domain_review',
                'groups':sorted({c['group'] for c in self.domain_model['classes']})}
