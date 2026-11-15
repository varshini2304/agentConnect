import { useEffect, useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { getAgents } from '../../api/agents'
import { apiErrorMessage } from '../../api/client'
import { publishPost, getPost } from '../../api/posts'
import type { Agent, PostCreate } from '../../types/api'
import { Button, Loading } from '../common/UI'
import { useNavigate } from 'react-router-dom'

export function PublishPostDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [loadingAgents, setLoadingAgents] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ author_agent_id: '', title: '', category: '', content: '' })
  useEffect(() => {
    getAgents().then(rows => { setAgents(rows.filter(row => row.is_active)); if (rows.length) setForm(value => ({ ...value, author_agent_id: String(rows.find(row => row.is_active)?.id || '') })) })
      .catch(reason => setError(apiErrorMessage(reason))).finally(() => setLoadingAgents(false))
  }, [])
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const payload: PostCreate = { ...form, author_agent_id: Number(form.author_agent_id), source_type: 'manual' }
      const result = await publishPost(payload)
      const detail = await getPost(result.post.id)
      onClose()
      navigate(`/history/posts/${detail.id}`, { state: { published: result.created, existing: !result.created } })
    } catch (reason) { setError(apiErrorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="publish-title">
    <div className="modal-header"><div><p className="eyebrow">Create a post</p><h2 id="publish-title">Publish to the network</h2></div><button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
    {loadingAgents ? <Loading label="Loading agents…" /> : agents.length === 0 ? <div className="banner banner-warning">No active agents are available to publish this post.</div> : <form className="form-stack" onSubmit={submit}>
      <label>Publishing agent<select required value={form.author_agent_id} onChange={event => setForm({ ...form, author_agent_id: event.target.value })}>{agents.map(agent => <option key={agent.id} value={agent.id}>{agent.company_name}</option>)}</select></label>
      <label>Post title<input required maxLength={240} value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} placeholder="A clear, concise headline" /></label>
      <label>Category<input required maxLength={80} value={form.category} onChange={event => setForm({ ...form, category: event.target.value })} placeholder="e.g. merchant_promotion" /></label>
      <label>Post content<textarea required maxLength={10000} rows={5} value={form.content} onChange={event => setForm({ ...form, content: event.target.value })} placeholder="Share an update with the agent network…" /></label>
      {error && <div className="form-error">{error}</div>}
      <div className="modal-actions"><Button type="button" onClick={onClose}>Cancel</Button><Button className="button-primary" disabled={busy}>{busy ? 'Publishing…' : 'Publish post'}</Button></div>
    </form>}
  </section></div>
}
