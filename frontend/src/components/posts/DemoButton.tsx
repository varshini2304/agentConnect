import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPost, runDemo } from '../../api/posts'
import { getAgents } from '../../api/agents'
import { Button } from '../common/UI'
import { get } from '../../workspace/api'
import { ActionNotice, Resource, useAction, useResource } from '../../workspace/common'
import { useSession } from '../../workspace/Session'
type Scenario = { scenario_id: string; title: string; category: string; available: boolean; author_agent_id: number | null }
export function DemoButton({ compact = false }: { compact?: boolean }) {
  const { can } = useSession()
  const [open, setOpen] = useState(false)
  return can('posts.publish') && can('workflow.run') ? <div className="demo-control"><Button className={compact ? 'button-small' : 'button-primary'} onClick={() => setOpen(!open)}>{open ? 'Close demo picker' : 'Run demo workflow'}</Button>{open && <DemoPicker />}</div> : null
}
function DemoPicker() {
  const { can } = useSession()
  const navigate = useNavigate()
  const action = useAction()
  const resource = useResource(async () => { const [scenarios, agents] = await Promise.all([get<Scenario[]>('/demo/scenarios'), can('agents.read') ? getAgents() : Promise.resolve([])]); return { scenarios, agents: agents.filter(agent => agent.is_active) } })
  return <div className="demo-picker card"><Resource resource={resource}>{data => <form className="form-stack" onSubmit={event => { event.preventDefault(); const values = new FormData(event.currentTarget); const scenario = data.scenarios.find(row => row.scenario_id === values.get('scenario')); const author = Number(values.get('author')) || scenario?.author_agent_id || undefined; void action.run(async () => { const result = await runDemo(String(values.get('scenario')), author); const detail = await getPost(result.post.id); navigate(`/history/posts/${detail.id}`, { state: { demo: true, created: result.created, missingKey: detail.interactions.some(item => item.status === 'failed' && item.error?.startsWith('missing_api_key:')) } }) }) }}><label>Available scenario<select name="scenario" required>{data.scenarios.map(row => <option key={row.scenario_id} value={row.scenario_id}>{row.title}</option>)}</select></label><label>Company author<select name="author"><option value="">Use the scenario’s existing company author</option>{data.agents.map(agent => <option key={agent.id} value={agent.id}>{agent.company_name}</option>)}</select></label><p className="muted">The workflow uses only agents owned by this company. Choose an active company agent if the original scenario author is unavailable.</p><ActionNotice action={action} /><Button type="submit" className="button-primary" disabled={action.busy || !data.scenarios.length}>{action.busy ? 'Running workflow…' : 'Run selected workflow'}</Button></form>}</Resource></div>
}
