import {useEffect, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {api, post, put, Row} from '../api/client';
import {ErrorBox, Notice, Status} from './shared';

export default function EmbeddingSettings() {
  const qc = useQueryClient();
  const {data, error: loadError} = useQuery({
    queryKey: ['/embedding-settings'], queryFn: () => api('/embedding-settings'),
    refetchInterval: query => ['pending', 'running'].includes(query.state.data?.last_job?.status) ? 2000 : false,
  });
  const [form, setForm] = useState<Row>();
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setForm({embedding_provider: data.embedding_provider, embedding_model: data.embedding_model,
      embedding_dimensions: data.embedding_dimensions, expected_version: data.version});
  }, [data?.version]);
  const rebuilding = ['pending', 'running'].includes(data?.last_job?.status);
  const choice = data?.options.find((option: Row) => option.provider === form?.embedding_provider && option.model === form?.embedding_model);
  const changed = form && data && (form.embedding_provider !== data.embedding_provider ||
    form.embedding_model !== data.embedding_model || form.embedding_dimensions !== data.embedding_dimensions);
  async function act(fn: () => Promise<Row>) {
    setBusy(true); setError(undefined); setMessage('');
    try { const result = await fn(); setMessage(result.status); await qc.invalidateQueries(); }
    catch (reason) { setError(reason); }
    finally { setBusy(false); }
  }
  return <section className="embedding-panel">
    <h2>Search embeddings</h2>
    <p>Choose how report text and search queries are embedded. Each model uses its own index.</p>
    {data && form ? <>
      <div className="form-row">
        <label>Embedding provider and model
          <select value={form.embedding_provider + '|' + form.embedding_model} disabled={busy || rebuilding}
            onChange={event => {
              const [provider, model] = event.target.value.split('|');
              const option = data.options.find((entry: Row) => entry.provider === provider && entry.model === model);
              setForm({...form, embedding_provider: provider, embedding_model: model, embedding_dimensions: option?.dimensions || 0});
            }}>
            {data.options.map((option: Row) => <option key={option.provider + option.model} value={option.provider + '|' + option.model}>
              {option.provider === 'fireworks' ? option.label : option.label + ' · ' + option.model.split('/').at(-1)}
            </option>)}
            <option value="disabled|">Disabled · exact and keyword search</option>
          </select>
        </label>
        <label>Embedding dimensions
          <input type="number" min={form.embedding_provider === 'disabled' ? 0 : 1} max={choice?.dimensions || 4096}
            value={form.embedding_dimensions} disabled={busy || rebuilding || ['local_bge', 'disabled'].includes(form.embedding_provider)}
            onChange={event => setForm({...form, embedding_dimensions: Number(event.target.value)})}/>
        </label>
      </div>
      <p>{form.embedding_provider === 'local_bge' ? 'Local processing; no external API key.' :
        form.embedding_provider === 'disabled' ? 'Semantic embeddings disabled.' :
        `${form.embedding_provider === 'openai' ? 'OPENAI_API_KEY' : 'FIREWORKS_API_KEY'} in .env: ${data.credentials[form.embedding_provider] ? 'configured' : 'not configured'}. Restart the app after adding a key.`}</p>
      {['openai', 'fireworks'].includes(form.embedding_provider) ? <Notice>Hosted embeddings send report text chunks and search queries to the selected provider. Original files and image pixels stay local.</Notice> : null}
      <div className="embedding-actions">
        <button className="primary" disabled={busy || rebuilding || !changed}
          onClick={() => act(() => put('/embedding-settings', form))}>Save embedding choice</button>
        <button disabled={busy || rebuilding || !!changed || !data.credential_configured || !data.total_documents || form.embedding_provider === 'disabled'}
          onClick={() => act(() => post('/embedding-settings/reindex'))}>Rebuild search index</button>
      </div>
      <p>Saved index: <Status value={data.index_state}/> · {data.indexed_documents} of {data.total_documents} published documents match.</p>
      {data.last_job ? <p role="status">Last rebuild: {data.last_job.status} · {data.last_job.completed_documents} of {data.last_job.total_documents} documents.
        {data.last_job.error ? <span className="embedding-error"> {data.last_job.error}</span> : null}</p> : null}
      <Notice>These OpenAI and Qwen models embed text. Configure image embeddings separately below.</Notice>
    </> : <p>Loading embedding configuration…</p>}
    {message ? <Notice>{message}</Notice> : null}
    <ErrorBox error={error || loadError}/>
  </section>;
}
