import {describe,it,expect} from 'vitest';
import {cpToUtf16} from './client';
describe('Source offset conversion',()=>{
 it('preserves non-BMP and combining source ranges in DOM highlights',()=>{
  const source='A😀e\u0301B';
  const start=cpToUtf16(source,1);const end=cpToUtf16(source,4);
  expect(source.slice(start,end)).toBe('😀e\u0301');
  expect(end).toBe(5);
 });
});
