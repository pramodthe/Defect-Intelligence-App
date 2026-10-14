"""Read-only LangChain tools, scoped to a saved run's publication manifest."""
from langchain_core.tools import StructuredTool
from typing import Any, Callable
from app.retrieval import search, source, enumerate_findings, evidence_media, manifest_chunks
from app.projections import NeoProjection
from app.research_evidence import compact_metadata


class ResearchToolInputError(ValueError):
    """A model can correct these arguments; canonical/service failures still propagate."""


def tool_registry(store, ontology, manifest_id, run_id=None):
    _, projections = manifest_chunks(store, manifest_id)
    documents = {p['document_id'] for p in projections}

    def search_precedents(query: str, limit: int = 12) -> dict:
        """Search report passages for observations, reasoning and repair options. Return source anchor IDs."""
        if not query.strip() or len(query) > 2000 or not 1 <= limit <= 24:
            raise ResearchToolInputError('Search requires a query and a limit between 1 and 24')
        return search(store, ontology, query, manifest_id, limit=limit)

    def get_exact_source(anchor_id: str) -> dict:
        """Read an exact source passage by an anchor ID returned by another tool. Preserve qualifications."""
        anchor = store.one('SELECT document_id FROM anchors WHERE id=?', (anchor_id,))
        if not anchor:
            raise ResearchToolInputError('Unknown source anchor. Copy an ID from anchor_ids verbatim; passage/chunk IDs are not source anchors.')
        if anchor['document_id'] not in documents:
            raise ResearchToolInputError('Source outside the pinned report library')
        return source(store, anchor_id)

    def list_findings(query: str = '') -> dict:
        """Enumerate finding identifiers and locations. Use for count/all questions; preserve coverage limits."""
        return enumerate_findings(store, query, manifest_id, limit=100)

    def find_report_images(query: str) -> dict:
        """Find original report figures and photographs by caption/OCR/context; this does not interpret pixels."""
        return evidence_media(store, ontology, query, manifest_id, limit=12)

    def get_report_sections(item_ids: list[str]) -> dict:
        """Read complete published original report sections, including reasoning and separate repair options, for item IDs returned by search."""
        if not item_ids or len(item_ids) > 3 or any(not store.one(
                'SELECT id FROM items WHERE id=? AND document_id IN (SELECT document_id FROM manifest_members WHERE manifest_id=?)',
                (iid, manifest_id)) for iid in item_ids):
            raise ResearchToolInputError('Use one to three report item IDs returned by search in the pinned library')
        from app.drafting import section_chunks
        return section_chunks(store, manifest_id, item_ids)

    def get_applicable_requirements() -> dict:
        """Retrieve exact original requirements established by this run's reviewed applicability decision. Missing coverage is a gap; a report citation is not governing authority."""
        from app.drafting import applicable_requirements
        return applicable_requirements(store, run_id, manifest_id)

    def expand_relationships(item_ids: list[str]) -> dict:
        """Follow Neo4j relationships for defect item IDs returned by search, retaining source support."""
        if len(item_ids) > 6:
            raise ResearchToolInputError('Graph expansion accepts at most six report items')
        if any(not store.one('SELECT id FROM items WHERE id=? AND document_id IN (SELECT document_id FROM manifest_members WHERE manifest_id=?)',
                            (iid, manifest_id)) for iid in item_ids):
            raise ResearchToolInputError('Graph item outside pinned library')
        revisions = [p['id'] for p in projections]
        paths = NeoProjection(store).neighbors(item_ids, revisions) if store.config.neo4j_uri else []
        from app.domain import published_snapshots
        qualified = {r['id']:r for snapshot in published_snapshots(store,manifest_id) for r in snapshot['relations']}
        for path in paths:
            assertion = qualified.get(path['assertion_id'])
            if assertion:
                path['qualified_assertion'] = {k:assertion[k] for k in ('predicate','scope','anchor_ids','statement_kind','review_state','reference_verification','applicability','repair_outcome','certainty')}
        anchors = sorted({s['anchor_id'] for path in paths for s in store.all(
            'SELECT anchor_id FROM assertion_support WHERE assertion_id=?', (path['assertion_id'],))} |
            {aid for path in paths for aid in qualified.get(path['assertion_id'],{}).get('anchor_ids',[])})
        return {'relationships': paths, 'anchor_ids': anchors[:100],
                'warnings': [] if store.config.neo4j_uri else ['Neo4j unconfigured']}

    functions: list[Callable[..., Any]] = [search_precedents, get_exact_source, list_findings, find_report_images,
                                         expand_relationships, get_report_sections, get_applicable_requirements]
    return {function.__name__: StructuredTool.from_function(function) for function in functions}


def model_view(name, result):
    """Bound tool output before sending selected text to the provider; canonical results stay local."""
    if result.get('error'):
        return result
    if name in {'search_precedents', 'get_report_sections', 'get_applicable_requirements'}:
        return {'items': [{**{k: e.get(k) for k in ('id', 'header', 'text', 'anchor_ids', 'retrieval_methods')},
                           'metadata': compact_metadata(e['metadata'])}
                          for e in result['items']], 'warnings': result.get('warnings', []),
                'coverage': result.get('coverage'), 'decision': result.get('decision')}
    if name == 'get_exact_source':
        return {**{k: result.get(k) for k in ('id', 'document_id', 'quote', 'content_kind', 'locator')},
                **({'block_context': result['text']} if result['text'] != result['quote'] else {})}
    if name == 'find_report_images':
        return {'items': [{k: e.get(k) for k in ('id', 'caption', 'role', 'identity', 'anchor_ids')}
                          for e in result['items']], 'warnings': result.get('warnings', [])}
    return result


def merge_tool_result(bundle, name, result):
    if result.get('error'):
        return bundle
    if name in {'search_precedents', 'get_report_sections', 'get_applicable_requirements'}:
        by_id = {e['id']: e for e in bundle.get('items', [])}
        by_id.update({e['id']: e for e in result['items']})
        bundle['items'] = list(by_id.values())
        if name == 'get_applicable_requirements':
            bundle['requirements'] = {k: result.get(k) for k in ('coverage', 'warnings', 'decision')}
    elif name == 'get_exact_source':
        sources = bundle.setdefault('sources', {})
        sources[result['id']] = result
    elif name == 'list_findings':
        bundle['enumeration'] = result
    elif name == 'find_report_images':
        bundle['media'] = result['items']
    elif name == 'expand_relationships':
        bundle['graph_anchor_ids'] = sorted(set(bundle.get('graph_anchor_ids', []) + result['anchor_ids']))
    return bundle
