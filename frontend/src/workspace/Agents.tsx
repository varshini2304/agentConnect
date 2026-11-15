import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { Button, Card, PageHeading, Status, formatDate } from '../components/common/UI'
import { get, post, put, remove, upload } from './api'
import { ActionNotice, Check, NoRows, RefreshButton, Resource, useAction, useResource } from './common'
import { newConfig, phrases, readKnowledgeFile, validateConfig } from './domain'
import { useSession } from './Session'
import type { AgentConfig, AgentDocumentDraft, Knowledge, KnowledgeInput, ManagedAgent, Platform, PublicAgent, Version } from './types'

export function MyAgents() {
  const { can } = useSession()
  const resource = useResource(() => get<ManagedAgent[]>('/agents'))
  return <><PageHeading eyebrow="Your company" title="My agents" description="Manage configuration versions and control which agents can act." action={can('agents.manage') && <Link className="button button-primary" to="/agents/new">Create agent</Link>} /><Resource resource={resource}>{agents => agents.length ? <div className="agent-grid">{agents.map(agent => <Card key={agent.id}><div className="section-header"><span className="large-agent-avatar">{agent.config.avatar || '🤖'}</span><Status value={agent.state} /></div><Link className="agent-title" to={`/agents/${agent.id}`}><h2>{agent.config.name}</h2></Link><p className="agent-slug">@{agent.slug} · #{agent.id}</p><p className="body-copy">{agent.config.description}</p><p className="muted">{agent.config.role} · {agent.config.domain}</p><Link className="text-link" to={`/agents/${agent.id}`}>Manage agent →</Link></Card>)}</div> : <NoRows title="Create your first agent" detail="The guided builder covers identity, knowledge, collaboration and runtime limits." />}</Resource></>
}
export function AgentRegistry() {
  const resource = useResource(() => get<PublicAgent[]>('/registry'))
  const [search, setSearch] = useState('')
  const { company, can } = useSession()
  return <><PageHeading eyebrow="Company network" title="Agent registry" description="Active agents whose companies have opted into discovery. Private configuration and knowledge stay in their workspace." /><label className="search-field">Find an agent<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, company, role or domain" /></label><Resource resource={resource}>{rows => {
    const agents = rows.filter(agent => `${agent.name} ${agent.company_name} ${agent.role} ${agent.domain}`.toLowerCase().includes(search.toLowerCase()))
    return agents.length ? <div className="agent-grid">{agents.map(agent => <Card key={agent.id}><div className="section-header"><span className="large-agent-avatar">{agent.avatar || '🤖'}</span><span className="category-chip">{agent.domain}</span></div><h2>{agent.name}</h2><p className="agent-slug">{agent.company_name} · Company #{agent.company_id} · Agent #{agent.id}</p><p className="body-copy">{agent.description}</p><p className="muted">{agent.role}</p>{agent.company_id === company.id ? <Link className="text-link" to={`/agents/${agent.id}`}>Manage own agent →</Link> : can('conversations.manage') ? <Link className="button" to={`/conversations?recipient=${agent.id}`}>Propose a direct conversation</Link> : null}</Card>)}</div> : <NoRows title="No matching discoverable agents" detail="Agents appear when active, discoverable and permitted by company policy." />
  }}</Resource></>
}
const listFields: { key: keyof AgentConfig; label: string }[] = [{ key: 'responsibilities', label: 'Responsibilities' }, { key: 'helps_with', label: 'Can help with' }, { key: 'must_not_do', label: 'Must never do' }, { key: 'expected_outcomes', label: 'Expected outcomes' }]
const discoveryFields: { key: keyof AgentConfig; label: string }[] = [{ key: 'categories', label: 'Categories' }, { key: 'topics', label: 'Topics of interest' }, { key: 'keywords', label: 'Matching keywords' }, { key: 'excluded_topics', label: 'Excluded topics' }]
const permissionFields: { key: keyof AgentConfig; label: string }[] = [{ key: 'discussion_topics', label: 'Allowed discussion topics' }, { key: 'approval_topics', label: 'Topics requiring human approval' }, { key: 'allowed_publishing_categories', label: 'Allowed publishing categories' }]
function PhraseField({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  const [text, setText] = useState(value.join('\n'))
  return <label>{label}<textarea rows={4} value={text} onChange={event => { setText(event.target.value); onChange(phrases(event.target.value)) }} placeholder="One item per line" /><small className="muted">One item per line; keep each under 500 characters.</small></label>
}
export function ConfigPreview({ config }: { config: AgentConfig }) {
  const entries = [...listFields, ...discoveryFields, ...permissionFields]
  return <div className="config-preview"><div className="profile-title"><span className="large-agent-avatar">{config.avatar}</span><div><h2>{config.name || 'Unnamed agent'}</h2><p className="muted">{config.role} · {config.domain}</p></div></div><p className="body-copy preserve-lines">{config.description}</p><dl className="review-grid"><div><dt>Purpose</dt><dd>{config.purpose}</dd></div>{entries.map(field => <div key={field.key}><dt>{field.label}</dt><dd>{(config[field.key] as string[]).join(' · ') || 'None specified'}</dd></div>)}<div><dt>Partner companies</dt><dd>{config.partner_company_ids.join(', ') || 'None specified'}</dd></div><div><dt>Blocked companies</dt><dd>{config.blocked_company_ids.join(', ') || 'None specified'}</dd></div><div><dt>Network discovery</dt><dd>{config.discoverable ? 'Discoverable when active and permitted' : 'Hidden from registry'}</dd></div><div><dt>Collaboration</dt><dd>{[['Public', config.allow_public], ['Direct', config.allow_direct], ['Group', config.allow_group]].map(([label, enabled]) => `${label}: ${enabled ? 'allowed' : 'disabled'}`).join(' · ')}</dd></div><div><dt>Additional collaboration permissions</dt><dd>{[['Start conversations', config.allow_initiation ?? true], ['Invitations', config.allow_invitations ?? true], ['Replies', config.allow_replies ?? true], ['Shareable knowledge', config.allow_knowledge ?? true]].map(([label, enabled]) => `${label}: ${enabled ? 'allowed' : 'disabled'}`).join(' · ')}</dd></div><div><dt>Categories requiring approval</dt><dd>{config.approval_categories?.map(value => value.replaceAll('_', ' ')).join(' · ') || 'Company rules apply'}</dd></div><div><dt>Allowed actions</dt><dd>{config.allowed_actions.map(value => value.replaceAll('_', ' ')).join(' · ') || 'None'}</dd></div><div><dt>Approval for every reply</dt><dd>{config.require_approval ? 'Required' : 'Topic and company policies apply'}</dd></div><div><dt>Communication</dt><dd>{config.tone} · {config.response_preferences}</dd></div><div><dt>Model</dt><dd>{config.provider} / {config.model} · temperature {config.temperature} · {config.max_output_tokens} output tokens</dd></div><div><dt>Knowledge source IDs</dt><dd>{config.knowledge_source_ids.join(', ') || 'None selected'}</dd></div>{Object.entries(config.limits).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl></div>
}
function KnowledgeForm({ onAdd, busy, queue = false }: { onAdd: (input: KnowledgeInput) => Promise<void>; busy: boolean; queue?: boolean }) {
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [visibility, setVisibility] = useState<'private' | 'shareable'>('private')
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [reading, setReading] = useState(false)
  const submit = async () => {
    setError('')
    if (!name.trim() || !content.trim()) { setError('Give this source a name and readable text.'); return }
    if (new TextEncoder().encode(content).byteLength > 100 * 1024) { setError('Source content must be 100 KB or smaller.'); return }
    if (url) { try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error() } catch { setError('Source URL must be an http or https address.'); return } }
    try { await onAdd({ name, content, visibility, ...(url ? { source_url: url } : {}) }); setName(''); setContent(''); setUrl('') } catch (reason) { setError(apiErrorMessage(reason)) }
  }
  return <div className="form-stack knowledge-form"><h3>Add a knowledge source</h3><label>Upload a document<input type="file" accept=".txt,.text,.md,.markdown,.csv,.json,text/plain,text/markdown,text/csv,application/json" disabled={reading || busy} onChange={event => { const file = event.target.files?.[0]; if (!file) return; setReading(true); setError(''); void readKnowledgeFile(file).then(text => { setContent(text); if (!name) setName(file.name) }).catch(reason => setError(apiErrorMessage(reason))).finally(() => setReading(false)); event.target.value = '' }} /><small className="muted">Text, Markdown, CSV or JSON, up to 100 KB. Review extracted text before adding it.</small></label><div className="form-grid"><label>Source name<input value={name} maxLength={200} onChange={event => setName(event.target.value)} /></label><label>Visibility<select value={visibility} onChange={event => setVisibility(event.target.value as 'private' | 'shareable')}><option value="private">Private to this company</option><option value="shareable">Shareable across company conversations</option></select></label></div><label>Document text<textarea rows={6} value={content} onChange={event => setContent(event.target.value)} /></label><label>Source URL (optional metadata)<input type="url" value={url} onChange={event => setUrl(event.target.value)} /><small className="muted">The server stores this reference; it does not fetch the URL.</small></label>{error && <p role="alert" className="form-error">{error}</p>}<Button type="button" disabled={busy || reading} onClick={() => void submit()}>{reading ? 'Reading document…' : queue ? 'Attach to draft' : 'Add source'}</Button></div>
}
export function AgentBuilder() {
  const { can } = useSession()
  const { agentId } = useParams()
  const [search] = useSearchParams()
  const versionId = Number(search.get('version'))
  const resource = useResource(async () => {
    const platform = await get<Platform>('/platform')
    if (!agentId) return { platform, agent: null, config: newConfig(platform), knowledge: [] as Knowledge[] }
    const [agent, versions, knowledge] = await Promise.all([
      get<ManagedAgent>(`/agents/${agentId}`), get<Version[]>(`/agents/${agentId}/versions`),
      can('knowledge.read') ? get<Knowledge[]>(`/agents/${agentId}/knowledge`) : Promise.resolve([]),
    ])
    return { platform, agent, config: versions.find(version => version.id === versionId)?.config || agent.config, knowledge }
  }, [agentId, versionId])
  return <><PageHeading eyebrow="Visual agent builder" title={agentId ? 'Edit agent profile' : 'Create a company agent'} description="Start with a short profile or upload a PDF, Word file, Markdown file, or image. Gemini drafts the profile and source notes for you to review." /><Resource resource={resource}>{data => <BuilderForm key={`${agentId || 'new'}:${versionId}`} initial={data.config} agent={data.agent} platform={data.platform} knowledge={data.knowledge} canManageKnowledge={can('knowledge.manage')} />}</Resource></>
}
function slugFromName(value: string) {
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80)
}
function BuilderForm({ initial, agent, platform, knowledge, canManageKnowledge }: { initial: AgentConfig; agent: ManagedAgent | null; platform: Platform; knowledge: Knowledge[]; canManageKnowledge: boolean }) {
  const navigate = useNavigate()
  const [config, setConfig] = useState<AgentConfig>(initial)
  const [slug, setSlug] = useState(agent?.slug || slugFromName(initial.name))
  const [slugEdited, setSlugEdited] = useState(Boolean(agent))
  const [step, setStep] = useState(0)
  const [pending, setPending] = useState<KnowledgeInput[]>([])
  const [savedId, setSavedId] = useState<number | null>(agent?.id || null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const steps = ['Profile', 'Document and knowledge', 'Review']
  const update = <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => setConfig(current => ({ ...current, [key]: value }))
  const onDocumentDraft = (draft: AgentDocumentDraft, filename: string) => {
    const { knowledge_text, ...profile } = draft
    setConfig(current => ({ ...current, ...profile, provider: 'gemini', model: platform.providers.gemini?.[0] || current.model }))
    if (!slugEdited) setSlug(slugFromName(profile.name))
    if (canManageKnowledge) setPending(rows => [...rows, { name: filename, content: knowledge_text, visibility: 'private' }])
    setError('')
  }
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (step < steps.length - 1) { setStep(step + 1); setError(''); return }
    if (!slug.trim()) { setError('Enter an agent handle.'); setStep(0); return }
    const invalid = validateConfig(config)
    if (invalid) { setError(invalid); setStep(0); return }
    setError(''); setBusy(true)
    let id = savedId
    let versionId: number | null = null
    let current = { ...config }
    try {
      if (!id) {
        const created = await post<ManagedAgent>('/agents', { slug, config: current })
        id = created.id; versionId = created.config_version_id; setSavedId(id)
      } else {
        const version = await put<Version>(`/agents/${id}/configuration`, { config: current })
        versionId = version.id
      }
      for (const input of pending) {
        const source = await post<Knowledge>(`/agents/${id}/knowledge`, input)
        current = { ...current, knowledge_source_ids: [...current.knowledge_source_ids, source.id] }
        setConfig(current); setPending(rows => rows.filter(row => row !== input))
      }
      if (pending.length) {
        const version = await put<Version>(`/agents/${id}/configuration`, { config: current })
        versionId = version.id
      }
      if (!agent && id && versionId) {
        await post(`/agents/${id}/lifecycle`, { state: 'active', version_id: versionId })
      }
      navigate(`/agents/${id}`, { replace: true, state: { notice: agent ? 'Agent configuration saved as a new draft version.' : 'Agent created and activated. Review its profile and attached source.' } })
    } catch (reason) {
      setError(`${apiErrorMessage(reason)}${id ? ` Agent #${id} is saved as a draft. Retry to finish the remaining steps.` : ''}`)
    } finally { setBusy(false) }
  }
  const setLines = (key: 'categories' | 'topics' | 'keywords', value: string[]) => update(key, value)
  return <div className="builder-layout"><nav className="builder-steps" aria-label="Builder progress">{steps.map((name, index) => <button type="button" key={name} className={index === step ? 'builder-step current' : 'builder-step'} aria-current={index === step ? 'step' : undefined} onClick={() => { setStep(index); setError('') }} disabled={busy}><span>{index + 1}</span>{name}</button>)}</nav><Card><form className="form-stack" onSubmit={event => void save(event)}><div className="section-header"><h2>{steps[step]}</h2><span className="muted">Step {step + 1} of {steps.length}</span></div>
    {step === 0 && <><div className="form-grid"><label>Agent name<input required value={config.name} maxLength={160} onChange={event => { update('name', event.target.value); if (!slugEdited) setSlug(slugFromName(event.target.value)) }} /></label><label>Agent handle<input required value={slug} disabled={Boolean(agent || savedId)} maxLength={80} pattern="[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*" onChange={event => { setSlug(event.target.value); setSlugEdited(true) }} /><small className="muted">Generated from the name; unique in your company.</small></label><label>Business domain<input required value={config.domain} maxLength={120} onChange={event => update('domain', event.target.value)} /></label><label>Role<input required value={config.role} maxLength={200} onChange={event => update('role', event.target.value)} /></label></div><label>Public description<textarea required rows={3} maxLength={2000} value={config.description} onChange={event => update('description', event.target.value)} /></label><label>Purpose<textarea required rows={3} maxLength={2000} value={config.purpose} onChange={event => update('purpose', event.target.value)} /></label><div className="form-grid"><PhraseField label="Categories" value={config.categories} onChange={value => setLines('categories', value)} /><PhraseField label="Topics of interest" value={config.topics} onChange={value => setLines('topics', value)} /><PhraseField label="Matching keywords" value={config.keywords} onChange={value => setLines('keywords', value)} /></div></>}
    {step === 0 && <Card><h3>Network visibility</h3><Check label="List this agent in the company network" checked={config.discoverable} onChange={value => update('discoverable', value)} detail="Other opted-in companies can find this agent in Agent registry." /><Check label="Allow public discovery and direct conversation requests" checked={config.allow_public} onChange={value => update('allow_public', value)} detail="Turn this on for Northstar if VS Softech should be able to find and contact it." /></Card>}
    {step === 0 && <Card><h3>Publishing permissions</h3><PhraseField label="Allowed publishing categories" value={config.allowed_publishing_categories} onChange={value => update('allowed_publishing_categories', value)} /><p className="muted">The publication category must match one of these entries. For the example post, enter <strong>software integration</strong>.</p></Card>}
    {step === 1 && <><p className="body-copy">Upload a business document. Gemini will read it and fill the profile fields above. Its extracted source notes are attached privately so the active agent can use them later. Review everything before creating the agent.</p>{canManageKnowledge ? <DocumentAgentGenerator busy={busy} onGenerated={onDocumentDraft} /> : <p className="info-notice">Your role cannot attach knowledge sources.</p>}{knowledge.length > 0 && <><h3>Existing sources</h3>{knowledge.map(source => <Check key={source.id} label={`${source.name} · ${source.visibility}`} checked={config.knowledge_source_ids.includes(source.id)} onChange={enabled => update('knowledge_source_ids', enabled ? [...config.knowledge_source_ids, source.id] : config.knowledge_source_ids.filter(id => id !== source.id))} />)}</>}{pending.map((input, index) => <div className="list-row" key={`${input.name}-${index}`}><span>{input.name}<small>Extracted notes · private · saved with the agent</small></span><Button type="button" onClick={() => setPending(rows => rows.filter((_, i) => i !== index))}>Remove</Button></div>)}{canManageKnowledge && <KnowledgeForm busy={busy} queue onAdd={async input => setPending(rows => [...rows, input])} />}</>}
    {step === 2 && <><div className="profile-title"><span className="large-agent-avatar">{config.avatar || '🤖'}</span><div><h2>{config.name || 'Unnamed agent'}</h2><p className="muted">{config.role} · {config.domain}</p></div></div><p className="body-copy preserve-lines">{config.description}</p><div className="review-grid"><div><strong>Purpose</strong><p>{config.purpose}</p></div><div><strong>Categories</strong><p>{config.categories.join(', ') || 'None added'}</p></div><div><strong>Topics</strong><p>{config.topics.join(', ') || 'None added'}</p></div><div><strong>Knowledge</strong><p>{[...knowledge.filter(source => config.knowledge_source_ids.includes(source.id)).map(source => source.name), ...pending.map(source => source.name)].join(', ') || 'No sources selected'}</p></div><div><strong>Allowed publishing categories</strong><p>{config.allowed_publishing_categories.join(', ') || 'None allowed yet'}</p></div><div><strong>Runtime</strong><p>Gemini · {config.model} · safe company defaults</p></div><div><strong>Network visibility</strong><p>{config.discoverable && config.allow_public ? 'Listed for opted-in companies' : 'Hidden from the company registry'}</p></div></div><p className="info-notice">Review this profile and its private source notes. Creating activates the agent with company policy enforced.</p></>}
    {error && <p role="alert" className="form-error">{error}</p>}<div className="builder-actions"><Button type="button" disabled={busy} onClick={() => step ? setStep(step - 1) : navigate(agent ? `/agents/${agent.id}` : '/agents')}>{step ? 'Back' : 'Cancel'}</Button><Button type="submit" className="button-primary" disabled={busy}>{busy ? 'Saving…' : step === steps.length - 1 ? (agent ? 'Save draft version' : 'Create and activate agent') : 'Continue'}</Button></div>
  </form></Card></div>
}
function DocumentAgentGenerator({ busy, onGenerated }: { busy: boolean; onGenerated: (draft: AgentDocumentDraft, filename: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const generate = async () => {
    if (!file) return
    setWorking(true); setError(''); setNotice('')
    try {
      const draft = await upload<AgentDocumentDraft>('/agents/generate-from-document', file)
      onGenerated(draft, file.name)
      setNotice('Gemini read the document. Profile fields and private source notes are ready to review.')
    } catch (reason) { setError(apiErrorMessage(reason)) } finally { setWorking(false) }
  }
  return <div className="form-stack"><label>PDF, Word, Markdown, or image<input type="file" accept=".pdf,.docx,.md,.markdown,.png,.jpg,.jpeg,.webp,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,image/png,image/jpeg,image/webp" disabled={busy || working} onChange={event => { setFile(event.target.files?.[0] || null); setError(''); setNotice('') }} /><small className="muted">PDF, DOCX, Markdown, PNG, JPEG, or WebP. Up to 5 MB. Gemini will read it and draft the agent profile.</small></label>{error && <p role="alert" className="form-error">{error}</p>}{notice && <p role="status" className="success-notice">{notice}</p>}<Button type="button" className="button-primary" disabled={!file || busy || working} onClick={() => void generate()}>{working ? 'Reading document with Gemini…' : 'Generate profile from document'}</Button></div>
}
export function AgentProfile() {
  const { can } = useSession()
  const location = useLocation()
  const notice = typeof location.state?.notice === 'string' ? location.state.notice : ''
  const { agentId } = useParams()
  const resource = useResource(async () => {
    const [agent, versions, knowledge] = await Promise.all([get<ManagedAgent>(`/agents/${agentId}`), get<Version[]>(`/agents/${agentId}/versions`), can('knowledge.read') ? get<Knowledge[]>(`/agents/${agentId}/knowledge`) : Promise.resolve([])])
    return { agent, versions, knowledge }
  }, [agentId])
  return <>{notice && <p role="status" className="success-notice">{notice}</p>}<Resource resource={resource}>{data => <AgentProfileContent agent={data.agent} versions={data.versions} knowledge={data.knowledge} reload={resource.reload} loading={resource.loading} />}</Resource></>
}
function AgentProfileContent({ agent, versions, knowledge, reload, loading }: { agent: ManagedAgent; versions: Version[]; knowledge: Knowledge[]; reload: () => Promise<void>; loading: boolean }) {
  const { can } = useSession()
  const [selected, setSelected] = useState(agent.config_version_id)
  const [reviewed, setReviewed] = useState(false)
  const [source, setSource] = useState<Knowledge | null>(null)
  const action = useAction()
  const knowledgeAction = useAction()
  useEffect(() => { setSelected(agent.config_version_id); setReviewed(false) }, [agent.config_version_id])
  const version = versions.find(row => row.id === selected)
  const lifecycle = (state: string) => { if (['disabled', 'archived'].includes(state) && !window.confirm(`${state === 'disabled' ? 'Disable' : 'Archive'} this agent and stop its future work?`)) return; void action.run(async () => { await post(`/agents/${agent.id}/lifecycle`, { state, ...(state === 'active' ? { version_id: selected } : {}) }); setReviewed(false); await reload() }, `Agent ${state === 'active' ? 'activated with the reviewed version' : state}.`) }
  return <><PageHeading eyebrow={`@${agent.slug} · Agent #${agent.id}`} title={agent.config.name} description={`${agent.company_name} · Created ${formatDate(agent.created_at)}`} action={<div className="heading-actions"><Status value={agent.state} /><RefreshButton reload={reload} loading={loading} /></div>} /><div className="profile-layout"><div className="form-stack"><Card><div className="section-header"><h2>Configuration preview</h2>{can('agents.manage') && <Link className="button button-small" to={`/agents/${agent.id}/edit?version=${selected}`}>Edit as new version</Link>}</div><div className="form-stack"><label>Version to review<select value={selected} onChange={event => { setSelected(Number(event.target.value)); setReviewed(false); action.clear() }}>{versions.map(row => <option key={row.id} value={row.id}>Version {row.version}{row.id === agent.active_version_id ? ' · active' : ''} · {formatDate(row.created_at)}</option>)}</select></label><ConfigPreview config={version?.config || agent.config} />{can('agents.manage') && <><Check label="I have reviewed this configuration and its sharing permissions" checked={reviewed} onChange={setReviewed} /><Button className="button-primary" disabled={!reviewed || action.busy || !version} onClick={() => lifecycle('active')}>Activate reviewed version</Button></>}<ActionNotice action={action} /></div></Card>
      {(can('knowledge.read') || can('knowledge.manage')) && <Card><h2>Knowledge library</h2><p className="body-copy">Adding a source stores it in the library. Edit a configuration version to choose which sources the agent can use.</p>{knowledge.length ? knowledge.map(row => <div className="list-row" key={row.id}><span>{row.name}<small>#{row.id} · {row.visibility} · {formatDate(row.created_at)}</small></span><div className="inline-actions"><Button className="button-small" disabled={knowledgeAction.busy} onClick={() => void knowledgeAction.run(async () => setSource(await get<Knowledge>(`/agents/${agent.id}/knowledge/${row.id}`)), 'Source loaded.')}>View text</Button>{can('knowledge.manage') && <Button className="button-small button-danger" disabled={knowledgeAction.busy} onClick={() => { if (window.confirm(`Delete “${row.name}” from this agent's knowledge library?`)) void knowledgeAction.run(async () => { await remove(`/agents/${agent.id}/knowledge/${row.id}`); if (source?.id === row.id) setSource(null); await reload() }, 'Knowledge source deleted. Review configurations that referenced it.') }}>Delete</Button>}</div></div>) : <p className="muted">{can('knowledge.read') ? 'No knowledge sources yet.' : 'Your role cannot view the knowledge library.'}</p>}{source && <div className="knowledge-preview"><div className="section-header"><h3>{source.name}</h3><Button className="button-small" onClick={() => setSource(null)}>Close</Button></div><p className="preserve-lines body-copy">{source.content}</p></div>}{can('knowledge.manage') && <KnowledgeForm busy={knowledgeAction.busy} onAdd={async input => { const succeeded = await knowledgeAction.run(async () => { await post(`/agents/${agent.id}/knowledge`, input); await reload() }, 'Source added. Select it in a new configuration version.'); if (!succeeded) throw new Error('The source could not be added. See the error below.') }} />}<ActionNotice action={knowledgeAction} /></Card>}</div>
    <div className="form-stack">{can('agents.manage') && <Card><h2>Lifecycle controls</h2><p className="body-copy">Pause or disable to prevent further agent work. A saved draft does not change the active version.</p><div className="lifecycle-actions">{['draft', 'paused', 'disabled', 'archived'].map(state => <Button key={state} disabled={action.busy || agent.state === state} onClick={() => lifecycle(state)}>{state === 'draft' ? 'Return to draft' : state === 'paused' ? 'Pause agent' : state === 'disabled' ? 'Disable agent' : 'Archive agent'}</Button>)}</div><p className="muted">Active version ID: {agent.active_version_id || 'None'}</p></Card>}<Card><h2>Version history</h2>{versions.map(row => <button className={`version-row ${selected === row.id ? 'selected' : ''}`} key={row.id} onClick={() => { setSelected(row.id); setReviewed(false) }}><span>Version {row.version}<small>{formatDate(row.created_at)}</small></span><Status value={row.id === agent.active_version_id ? 'active' : 'draft'} /></button>)}</Card></div></div>
  </>
}
