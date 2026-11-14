import { useCallback } from 'react'
import { ArrowUpRight, Bot, Building2, Tag, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getAgents } from '../api/agents'
import { Card, EmptyState, ErrorState, Loading, PageHeading, Status } from '../components/common/UI'
import { useApiData, useRefreshKey } from '../hooks/useApiData'

export function Agents() {
  const refreshKey = useRefreshKey()
  const load = useCallback(getAgents, [refreshKey])
  const { data, loading, error, reload } = useApiData(load, [load])
  return <>
    <PageHeading eyebrow="Company network" title="Agents" description="Registered company agents and the topics they follow." />
    {loading && !data ? <Loading label="Loading registered agents…" /> : error && !data ? <ErrorState message={error} retry={() => void reload()} /> : !data?.length ? <EmptyState title="No agents found" detail="The backend has not registered any agents yet." /> : <>
      {error && <div className="banner banner-warning">The agent list could not be refreshed: {error}</div>}
      <div className="agents-toolbar"><span><Users size={16} /> {data.length} agents registered</span><span className="muted">Profiles are managed by the backend</span></div>
      <div className="agent-grid">{data.map(agent => {
        const categories = agent.interests.filter(item => item.interest_type === 'category')
        const keywords = agent.interests.filter(item => item.interest_type === 'keyword')
        const exclusions = agent.interests.filter(item => item.interest_type === 'exclude')
        return <Card className="agent-card" key={agent.id}><div className="agent-card-head"><div className="large-agent-avatar">{agent.company_name.slice(0, 1)}</div><Status value={agent.is_active ? 'active' : 'inactive'} /></div><Link to={`/agents/${agent.id}`} className="agent-title"><h2>{agent.company_name}<ArrowUpRight size={16} /></h2></Link><p className="agent-slug">@{agent.slug}</p><p className="agent-description">{agent.description}</p><div className="agent-facts"><span><Building2 size={14} />{agent.industry.replaceAll('_', ' ')}</span><span>{agent.role}</span></div>
          <div className="interest-block"><h3><Tag size={14} /> Categories</h3><div className="chip-list">{categories.length ? categories.map(item => <span className="interest-chip" key={item.id}>{item.value.replaceAll('_', ' ')}</span>) : <small className="muted">None configured</small>}</div></div>
          <div className="interest-block"><h3>Keywords</h3><div className="chip-list">{keywords.length ? keywords.slice(0, 6).map(item => <span className="keyword-chip" key={item.id}>{item.value}</span>) : <small className="muted">None configured</small>}{keywords.length > 6 && <small className="muted">+{keywords.length - 6} more</small>}</div></div>
          {exclusions.length > 0 && <div className="agent-exclusions">Excludes: {exclusions.map(item => item.value).join(', ')}</div>}
          <Link className="agent-card-link" to={`/agents/${agent.id}`}>View profile <ArrowUpRight size={14} /></Link>
        </Card>
      })}</div>
    </>}
  </>
}
