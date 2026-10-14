import re
import time
from pydantic import BaseModel,Field
from app.store import Store,identity


class RenditionReview(BaseModel):
    canonical_finding_id:str
    alias_finding_id:str
    anchor_ids:list[str]=Field(min_length=2)
    reviewer:str=Field(min_length=3)
    reason:str=Field(min_length=10)
    same_report_version:bool


def confirm(store:Store,body:RenditionReview):
    if not body.same_report_version or body.canonical_finding_id==body.alias_finding_id:
        raise ValueError('Explicit same-version identity review of two distinct renditions required')
    sql='SELECT f.*,d.family_id,a.mime FROM findings f JOIN documents d ON d.id=f.document_id JOIN assets a ON a.id=d.asset_id WHERE f.id=?'
    canonical=store.require(sql,(body.canonical_finding_id,))
    alias=store.require(sql,(body.alias_finding_id,))
    if canonical['family_id']!=alias['family_id'] or canonical['document_id']==alias['document_id']:
        raise ValueError('Reviewed rendition identities must share their explicitly linked family')
    if {canonical['mime'],alias['mime']}!={'application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document'}:
        raise ValueError('This mapping supports distinct Word/PDF renditions, not report revisions')
    def normalize(text):
        return re.sub(r'\W','',text.lower())
    if normalize(canonical['identifier'])!=normalize(alias['identifier']) or normalize(canonical['location'])!=normalize(alias['location']):
        raise ValueError('Identifier/location conflict: retain distinct occurrences and review source identity')
    owners={store.require('SELECT document_id FROM anchors WHERE id=?',(aid,))['document_id'] for aid in body.anchor_ids}
    if owners!={canonical['document_id'],alias['document_id']}:
        raise ValueError('Support from both immutable source versions is required')
    if store.one('SELECT id FROM finding_equivalences WHERE alias_finding_id=? OR canonical_finding_id=?',(canonical['id'],alias['id'])):
        raise ValueError('Mapping would create a rendition identity chain/cycle')
    if store.one('SELECT id FROM finding_equivalences WHERE alias_finding_id=?',(alias['id'],)):
        raise ValueError('Alias already has a reviewed identity mapping; conflicting edits require a successor review')
    eid=identity('equivalence',body.model_dump())
    store.insert('finding_equivalences',{'id':eid,'canonical_finding_id':canonical['id'],'alias_finding_id':alias['id'],
        'anchor_ids':body.anchor_ids,'reviewer':body.reviewer,'reason':body.reason,'state':'confirmed','created':time.time()})
    store.execute('UPDATE runs SET stale=1 WHERE id IN (SELECT run_id FROM run_dependencies WHERE dependency_id IN (?,?))',(canonical['document_id'],alias['document_id']))
    projection=store.require('SELECT projection_id FROM manifest_members WHERE manifest_id=? AND document_id=?',(store.active_manifest(),canonical['document_id']))
    store.activate(projection['projection_id'],{'identity_review':'reviewed Word/PDF equivalence'})
    return {'id':eid,'state':'confirmed','physical_sources':'both retained; new enumeration avoids double counting'}
