import {describe,it,expect} from 'vitest';
import {phaseStatus,researchError,runActive} from './researchStatus';

describe('Stopped research progress',()=>{
 const events=[{sequence:1,type:'model_completed',payload:{node:'model_planning'}},{sequence:2,type:'model_started',payload:{node:'model_synthesis'}}];
 const run={status:'interrupted',error:'TimeoutError',answer:{},operations:[{node:'model_synthesis',state:'unknown',seconds_reserved:90}]};
 it('shows the timed-out phase and the verification that never ran',()=>{
  expect(phaseStatus(run,events,'model_synthesis')).toBe('timed out');
  expect(phaseStatus(run,events,'model_verification')).toBe('not run');
  expect(researchError(run,events)).toContain('90-second response limit');
  expect(runActive(run.status)).toBe(false);
 });
 it('does not report a running request as timed out',()=>{
  expect(phaseStatus({...run,status:'running',error:null},events,'model_synthesis')).toBe('running');
 });
 it('keeps a later interrupted planning attempt distinct from an earlier completed one',()=>{
  expect(phaseStatus(run,[...events,{sequence:3,type:'model_started',payload:{node:'model_planning'}}],'model_planning')).toBe('timed out');
 });
 it('preserves completed verification and explicit source-excerpt mode',()=>{
  expect(phaseStatus({status:'complete',answer:{model_calls:[{node:'model_verification'}]}},[],'model_verification')).toBe('completed');
  expect(phaseStatus({status:'partial',answer:{synthesis:'unavailable'}},[],'model_synthesis')).toBe('source excerpts only');
 });
});
