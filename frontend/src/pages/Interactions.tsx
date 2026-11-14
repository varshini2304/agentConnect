import { useCallback, useState } from 'react'
import { Activity, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getInteraction, retryInteraction } from '../api/interactions'
import { apiErrorMessage } from '../api/client'
import { getPosts, getPost } from '../api/posts'
import { getAgents } from '../api/agents'
import { Button, Card, EmptyState, ErrorState, formatDate, Loading, PageHeading, Status } from '../components/common/UI'
import { useApiData, useRefreshKey } from '../hooks/useApiData'
import type { Agent, Interaction, PostDetail } from '../types/api'

type Data = { details: PostDetail[]; agents: Agent[]; detailFailures: number }
export function Interactions() {
  const refreshKey = useRefreshKey()
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<Interaction | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const load = useCallback(async (): Promise<Data> => {
    const [feed, agents] = await Promise.all([getPosts(20, 0), getAgents()])
    const results = await Promise.allSettled(feed.items.map(post => getPost(post.id)))
    return { agents, details: results.flatMap(result => result.status === 'fulfilled' ? [result.value] : []), detailFailures: results.filter(result => result.status === 'rejected').length }
  }, [refreshKey])
  const { data, loading, error, reload } = useApiData(load, [load])
  const agentNames = new Map(data?.agents.map(agent => [agent.id, agent.company_name]) || [])
  const rows = data?.details.flatMap(detail => detail.interactions.map(interaction => ({ interaction, post: detail }))).sort((a, b) => b.interaction.started_at.localeCompare(a.interaction.started_at)) || []
  const inspect = async (row: Interaction) => {
    setSelected(row.id); setSelectedDetail(null); setActionError('')
    try { setSelectedDetail(await getInteraction(row.id)) } catch (reason) { setActionError(apiErrorMessage(reason)) }
  }
  const retry = async (id: number) => {
    setBusyId(id); setActionError(''); setNotice('')
    try {
      await retryInteraction(id)
      const postId = rows.find(row => row.interaction.id === id)?.interaction.post_id
      const [freshInteraction, refreshedPost] = await Promise.all([getInteraction(id), postId ? getPost(postId) : Promise.resolve(null)])
      setSelectedDetail(refreshedPost?.interactions.find(item => item.id === id) || freshInteraction)
      setNotice(freshInteraction.status === 'failed' ? 'Retry finished; the backend still reports a failed interaction.' : `Retry finished with status: ${freshInteraction.status}.`)
      await reload()
    } catch (reason) { setActionError(apiErrorMessage(reason)) }
    finally { setBusyId(null) }
  }
  return <>
    <PageHeading eyebrow="Agent decisions" title="Interactions" description="Decision and response records across the latest 20 posts." />
    <div className="banner banner-info">The API has interaction lookup by ID but no global interaction list. This view aggregates details for the latest 20 posts.</div>
    {notice && <div className="banner banner-success">{notice}</div>}{actionError && <div className="banner banner-warning">{actionError}</div>}
    {error && data && <div className="banner banner-warning">The interaction list could not be fully refreshed: {error}</div>}
    {data?.detailFailures ? <div className="banner banner-warning">{data.detailFailures} recent post detail record(s) could not be loaded; this list may be incomplete.</div> : null}
    {loading && !data ? <Loading label="Collecting recent interaction details…" /> : error && !data ? <ErrorState message={error} retry={() => void reload()} /> : !rows.length ? <EmptyState title="No agent interactions" detail="Interactions appear after the backend creates notifications for selected agents." /> : <div className="interaction-layout"><div className="interaction-list">{rows.map(({ interaction, post }) => <Card className={`interaction-card ${selected === interaction.id ? 'interaction-selected' : ''}`} key={interaction.id}><div className="interaction-card-top"><div className={`interaction-symbol symbol-${interaction.status}`}><Activity size={17} /></div><div className="interaction-heading"><strong>{agentNames.get(interaction.agent_id) || `Agent ${interaction.agent_id}`}</strong><span>{formatDate(interaction.started_at)}</span></div><Status value={interaction.status} /></div><Link to={`/posts/${post.id}`} className="interaction-post-title">{post.title}</Link><div className="interaction-card-actions"><Button className="button-small" onClick={() => void inspect(interaction)}>Details</Button>{interaction.status === 'failed' && <Button className="button-small retry-button" disabled={busyId === interaction.id} onClick={() => void retry(interaction.id)}><RotateCcw size={14} />{busyId === interaction.id ? 'Retrying…' : 'Retry'}</Button>}</div></Card>)}</div>
      <Card className="interaction-detail-panel">{selectedDetail ? <InteractionDetail interaction={selectedDetail} agentName={agentNames.get(selectedDetail.agent_id) || `Agent ${selectedDetail.agent_id}`} /> : <EmptyState title="Select an interaction" detail="Open a decision to inspect its backend response and timestamps." />}</Card>
    </div>}
  </>
}
function InteractionDetail({ interaction, agentName }: { interaction: Interaction; agentName: string }) {
  const decision = interaction.decision_json?.decision
  return <><p className="eyebrow">Interaction #{interaction.id}</p><h2>{agentName}</h2><div className="detail-status-line"><Status value={interaction.status} /><span className="muted">{interaction.decision_json?.provider || 'No provider recorded'}</span></div><h3>Decision reason</h3><p className="detail-description">{decision?.reason || interaction.error || 'No decision reason was recorded.'}</p>{interaction.comment && <><h3>Generated comment</h3><blockquote className="generated-comment">{interaction.comment.content}</blockquote></>}<div className="profile-definition"><span>Started</span><strong>{formatDate(interaction.started_at)}</strong><span>Completed</span><strong>{formatDate(interaction.completed_at)}</strong></div>{interaction.error && <div className="failure-detail"><strong>Failure detail</strong><p>{interaction.error}</p></div>}</>
}
