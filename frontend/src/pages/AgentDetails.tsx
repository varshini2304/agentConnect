import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getAgent, updateAgent } from '../api/agents'
import { apiErrorMessage } from '../api/client'
import type { Agent, AgentPatch, Interest } from '../types/api'
import { Button, Card, ErrorState, Loading, PageHeading, Status } from '../components/common/UI'
import { useRefreshKey } from '../hooks/useApiData'

type InterestRow = { interest_type: Interest['interest_type']; value: string; weight: number }
export function AgentDetails() {
  const { agentId = '' } = useParams()
  const id = Number(agentId)
  const refreshKey = useRefreshKey()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [form, setForm] = useState({ company_name: '', role: '', industry: '', description: '', is_active: true })
  const [interests, setInterests] = useState<InterestRow[]>([])
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const row = await getAgent(id); setAgent(row)
      setForm({ company_name: row.company_name, role: row.role, industry: row.industry, description: row.description, is_active: row.is_active })
      setInterests(row.interests.map(({ interest_type, value, weight }) => ({ interest_type, value, weight })))
    } catch (reason) { setError(apiErrorMessage(reason)) }
    finally { setLoading(false) }
  }, [id, refreshKey])
  useEffect(() => { void load() }, [load])
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      const payload: AgentPatch = { ...form, interests: interests.filter(item => item.value.trim()).map(item => ({ ...item, value: item.value.trim() })) }
      const saved = await updateAgent(id, payload); setAgent(saved); setEditing(false); setNotice('Agent profile saved to the backend.')
    } catch (reason) { setError(apiErrorMessage(reason)) }
    finally { setBusy(false) }
  }
  if (loading && !agent) return <><PageHeading title="Agent profile" /><Loading label="Loading agent profile…" /></>
  if (error && !agent) return <><PageHeading title="Agent profile" /><ErrorState message={error} retry={() => void load()} /></>
  if (!agent) return null
  return <>
    <Link to="/agents" className="back-link"><ArrowLeft size={15} /> All agents</Link>
    <PageHeading eyebrow={`Agent profile · @${agent.slug}`} title={agent.company_name} description="Company identity, operating role, and configured relevance interests." action={!editing && <Button onClick={() => setEditing(true)}>Edit profile</Button>} />
    {notice && <div className="banner banner-success">{notice}</div>}{error && <div className="banner banner-warning">{error}</div>}
    {editing ? <Card><form className="edit-agent-form" onSubmit={save}><div className="form-grid">
      <label>Company name<input required maxLength={160} value={form.company_name} onChange={event => setForm({ ...form, company_name: event.target.value })} /></label>
      <label>Industry<input required maxLength={120} value={form.industry} onChange={event => setForm({ ...form, industry: event.target.value })} /></label>
      <label className="form-wide">Role<input required maxLength={200} value={form.role} onChange={event => setForm({ ...form, role: event.target.value })} /></label>
      <label className="form-wide">Description<textarea required maxLength={2000} rows={3} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={form.is_active} onChange={event => setForm({ ...form, is_active: event.target.checked })} /> Agent is active</label>
    </div>
    <div className="form-section-heading"><div><h3>Interests and exclusions</h3><p className="muted">Changes update the persisted profile used by backend routing.</p></div><Button type="button" onClick={() => setInterests([...interests, { interest_type: 'keyword', value: '', weight: 1 }])}><Plus size={15} />Add interest</Button></div>
    <div className="interest-editor">{interests.map((item, index) => <div className="interest-edit-row" key={`${index}-${item.interest_type}`}><select aria-label="Interest type" value={item.interest_type} onChange={event => setInterests(interests.map((row, i) => i === index ? { ...row, interest_type: event.target.value as InterestRow['interest_type'] } : row))}><option value="category">Category</option><option value="keyword">Keyword</option><option value="exclude">Exclude</option></select><input aria-label="Interest value" value={item.value} placeholder="Interest value" onChange={event => setInterests(interests.map((row, i) => i === index ? { ...row, value: event.target.value } : row))} /><input aria-label="Interest weight" type="number" min="0" step="0.1" value={item.weight} onChange={event => setInterests(interests.map((row, i) => i === index ? { ...row, weight: Number(event.target.value) } : row))} /><button type="button" className="icon-button danger-icon" aria-label="Remove interest" onClick={() => setInterests(interests.filter((_, i) => i !== index))}><Trash2 size={16} /></button></div>)}</div>
    <div className="modal-actions"><Button type="button" onClick={() => { setEditing(false); void load() }}>Cancel</Button><Button className="button-primary" disabled={busy}><Save size={15} />{busy ? 'Saving…' : 'Save profile'}</Button></div></form></Card> : <div className="agent-detail-grid"><Card><div className="detail-profile-header"><div className="large-agent-avatar">{agent.company_name.slice(0, 1)}</div><div><Status value={agent.is_active ? 'active' : 'inactive'} /><p className="agent-slug">@{agent.slug} · joined {new Date(agent.created_at).toLocaleDateString()}</p></div></div><h2 className="detail-section-title">Company profile</h2><p className="detail-description">{agent.description}</p><div className="profile-definition"><span>Role</span><strong>{agent.role}</strong><span>Industry</span><strong>{agent.industry.replaceAll('_', ' ')}</strong></div></Card>
      <Card><h2 className="detail-section-title">Routing interests</h2><InterestGroup label="Categories" type="category" items={agent.interests} /><InterestGroup label="Keywords" type="keyword" items={agent.interests} /><InterestGroup label="Exclusions" type="exclude" items={agent.interests} /></Card></div>}
  </>
}
function InterestGroup({ label, type, items }: { label: string; type: Interest['interest_type']; items: Interest[] }) {
  const matching = items.filter(item => item.interest_type === type)
  return <div className="detail-interest-group"><h3>{label}<span>{matching.length}</span></h3><div className="chip-list">{matching.length ? matching.map(item => <span className={type === 'exclude' ? 'exclude-chip' : type === 'category' ? 'interest-chip' : 'keyword-chip'} key={item.id}>{item.value}</span>) : <small className="muted">No {label.toLowerCase()} configured.</small>}</div></div>
}
