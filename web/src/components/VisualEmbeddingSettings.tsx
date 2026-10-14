import {useEffect, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {api, post, put, Row} from '../api/client';
import {ErrorBox, Notice, Status} from './shared';

export default function VisualEmbeddingSettings() {
  const qc = useQueryClient();
  const {data: text} = useQuery({queryKey: ['/embedding-settings'], queryFn: () => api('/embedding-settings')});
  const rebuilding = ['pending', 'running'].includes(text?.last_job?.status);
  const {data, error: loadError} = useQuery({queryKey: ['/visual-embedding-settings'],
    queryFn: () => api('/visual-embedding-settings'), refetchInterval: rebuilding ? 2000 : false});
  const [form, setForm] = useState<Row>();
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setForm({expected_version: data.version, visual_embedding_provider: data.visual_embedding_provider,
      visual_embedding_deployment: data.visual_embedding_deployment, visual_embedding_dimensions: data.visual_embedding_dimensions,
      visual_embedding_enabled: data.visual_embedding_enabled});
  }, [data?.version]);
  const changed = data && form && ['visual_embedding_provider','visual_embedding_deployment','visual_embedding_dimensions','visual_embedding_enabled']
    .some(field => data[field] !== form[field]);
  const disabled = form?.visual_embedding_provider === 'disabled';
  const serverReady = data && !disabled && data.credentials[form?.visual_embedding_provider] &&
    (form?.visual_embedding_provider !== 'fireworks_voyage' || !!form.visual_embedding_deployment.trim());
  async function act(fn: () => Promise<Row>) {
    setBusy(true); setError(undefined); setMessage('');
    try {const result = await fn(); setMessage(result.status); await qc.invalidateQueries();}
    catch (reason) {setError(reason);}
    finally {setBusy(false);}
  }
  return <section className="embedding-panel visual-embedding-panel">
    <h2>Image embeddings</h2>
    <p>Use Voyage Multimodal 3.5 to retrieve original photos and figures from their pixels and source context.</p>
    {data && form ? <>
      <div className="form-row">
        <label>Visual embedding provider
          <select value={form.visual_embedding_provider} disabled={busy || rebuilding} onChange={event =>
            setForm({...form, visual_embedding_provider: event.target.value, visual_embedding_enabled: false})}>
            <option value="disabled">Disabled · OCR, captions and linked text</option>
            <option value="fireworks_voyage">Fireworks · Voyage Multimodal 3.5</option>
            <option value="voyage">Voyage direct · Multimodal 3.5</option>
          </select>
        </label>
        <label>Visual embedding dimensions
          <select value={form.visual_embedding_dimensions} disabled={busy || rebuilding || disabled}
            onChange={event => setForm({...form, visual_embedding_dimensions: Number(event.target.value)})}>
            {data.dimensions.map((dimension: number) => <option value={dimension} key={dimension}>{dimension}</option>)}
          </select>
        </label>
      </div>
      {form.visual_embedding_provider === 'fireworks_voyage' ? <>
        <label>Fireworks Voyage deployment path
          <input value={form.visual_embedding_deployment} disabled={busy || rebuilding}
            placeholder="accounts/your-account/deployments/your-deployment"
            onChange={event => setForm({...form, visual_embedding_deployment: event.target.value})}/>
        </label>
        <p>Fireworks requires a dedicated Voyage deployment. Its image input support must pass the synthetic test.</p>
      </> : null}
      {!disabled ? <p>{form.visual_embedding_provider === 'fireworks_voyage' ? 'FIREWORKS_API_KEY' : 'VOYAGE_API_KEY'} in .env:
        {' '}{data.credentials[form.visual_embedding_provider] ? 'configured' : 'not configured'}. Restart after changing a key.</p> : null}
      <label className="pixel-permission">
        <input type="checkbox" checked={form.visual_embedding_enabled} disabled={busy || rebuilding || disabled}
          onChange={event => setForm({...form, visual_embedding_enabled: event.target.checked})}/>
        Enable sending report images and captions to the selected provider
      </label>
      <Notice>The connection test uses two generated shapes and two text queries. Source images are processed only after enabling this setting, passing the test and rebuilding. Word/PDF originals remain local and unchanged.</Notice>
      <div className="embedding-actions">
        <button className="primary" disabled={busy || rebuilding || !changed}
          onClick={() => act(() => put('/visual-embedding-settings', form))}>Save visual settings</button>
        <button disabled={busy || rebuilding || !!changed || !serverReady}
          onClick={() => act(() => post('/visual-embedding-settings/test'))}>{busy ? 'Working…' : 'Test synthetic images'}</button>
        <button disabled={busy || rebuilding || !!changed || !data.configured || !text?.total_documents}
          onClick={() => act(() => post('/embedding-settings/reindex'))}>Rebuild image index</button>
      </div>
      <p>Image/text connection: <Status value={data.capability_verified ? 'verified' : 'not_verified'}/> ·
        {' '}Image index: <Status value={data.index_state}/> · {data.indexed_media} of {data.total_media} images indexed.
        {data.skipped_media ? ` ${data.skipped_media} unsupported or oversized images retain their originals and text search.` : ''}</p>
    </> : <p>Loading visual embedding configuration…</p>}
    {message ? <Notice>{message}</Notice> : null}
    <ErrorBox error={error || loadError}/>
  </section>;
}
