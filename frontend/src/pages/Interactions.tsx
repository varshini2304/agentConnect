import { useCallback, useState } from 'react'
import { Activity, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getInteraction, getInteractions, retryInteraction } from '../api/interactions'
import { apiErrorMessage } from '../api/client'
import { getPosts, getPost } from '../api/posts'
import { useSession } from '../workspace/Session'
import { HistoryNavigation } from '../workspace/History'
import { getAgents } from '../api/agents'
import { Button, Card, EmptyState, ErrorState, formatDate, Loading, PageHeading, Status } from '../components/common/UI'
import { useApiData, useRefreshKey } from '../hooks/useApiData'
import type { Agent, Interaction, Post } from '../types/api'

type Data = { interactions: Interaction[]; agents: Agent[]; posts: Post[] }
export function Interactions() {
  const { can } = useSession()
  const refreshKey = useRefreshKey()
  const [offset, setOffset] = useState(0)
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<Interaction | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const load = useCallback(async (): Promise<Data> => {
    const [interactions, feed, agents] = await Promise.all([getInteractions(50, offset), getPosts(100, 0), can('agents.read') ? getAgents() : Promise.resolve([])])
    return { interactions, agents, posts: feed.items }
  }, [offset, refreshKey])
  const { data, loading, error, reload } = useApiData(load, [load])
  const agentNames = new Map(data?.agents.map(agent => [agent.id, agent.company_name]) || [])
  const rows = data?.interactions.map(interaction => ({ interaction, post: data.posts.find(post => post.id === interaction.post_id) || { id: interaction.post_id, title: `Post #${interaction.post_id}` } })) || []
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
    <PageHeading eyebrow="Agent decisions" title="Interactions" description="Persisted agent decisions and responses for this company." />
    <HistoryNavigation /><div className="banner banner-info">Inspect prior decisions and responses. Authorized teammates can retry failed interactions.</div>
    {notice && <div className="banner banner-success">{notice}</div>}{actionError && <div className="banner banner-warning">{actionError}</div>}
    {error && data && <div className="banner banner-warning">The interaction list could not be fully refreshed: {error}</div>}
    {loading && !data ? <Loading label="Collecting recent interaction details…" /> : error && !data ? <ErrorState message={error} retry={() => void reload()} /> : !rows.length ? <EmptyState title="No agent interactions" detail="Interactions appear after the backend creates notifications for selected agents." /> : <div className="interaction-layout"><div className="interaction-list">{rows.map(({ interaction, post }) => <Card className={`interaction-card ${selected === interaction.id ? 'interaction-selected' : ''}`} key={interaction.id}><div className="interaction-card-top"><div className={`interaction-symbol symbol-${interaction.status}`}><Activity size={17} /></div><div className="interaction-heading"><strong>{agentNames.get(interaction.agent_id) || `Agent ${interaction.agent_id}`}</strong><span>{formatDate(interaction.started_at)}</span></div><Status value={interaction.status} /></div><Link to={`/history/posts/${post.id}`} className="interaction-post-title">{post.title}</Link><div className="interaction-card-actions"><Button className="button-small" onClick={() => void inspect(interaction)}>Details</Button>{can('workflow.run') && interaction.status === 'failed' && <Button className="button-small retry-button" disabled={busyId === interaction.id} onClick={() => void retry(interaction.id)}><RotateCcw size={14} />{busyId === interaction.id ? 'Retrying…' : 'Retry'}</Button>}</div></Card>)}</div>
      <Card className="interaction-detail-panel">{selectedDetail ? <InteractionDetail interaction={selectedDetail} agentName={agentNames.get(selectedDetail.agent_id) || `Agent ${selectedDetail.agent_id}`} /> : <EmptyState title="Select an interaction" detail="Open a decision to inspect its backend response and timestamps." />}</Card>
    </div>}
    <div className="pagination-bar"><Button disabled={!offset || loading} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><span>Page {Math.floor(offset / 50) + 1}</span><Button disabled={loading || (data?.interactions.length || 0) < 50} onClick={() => setOffset(offset + 50)}>Next</Button></div>
  </>
}
function InteractionDetail({ interaction, agentName }: { interaction: Interaction; agentName: string }) {
  const decision = interaction.decision_json?.decision
  return <><p className="eyebrow">Interaction #{interaction.id}</p><h2>{agentName}</h2><div className="detail-status-line"><Status value={interaction.status} /><span className="muted">{interaction.decision_json?.provider || 'No provider recorded'}</span></div><h3>Decision reason</h3><p className="detail-description">{decision?.reason || interaction.error || 'No decision reason was recorded.'}</p>{interaction.comment && <><h3>Generated comment</h3><blockquote className="generated-comment">{interaction.comment.content}</blockquote></>}<div className="profile-definition"><span>Started</span><strong>{formatDate(interaction.started_at)}</strong><span>Completed</span><strong>{formatDate(interaction.completed_at)}</strong></div>{interaction.error && <div className="failure-detail"><strong>Failure detail</strong><p>{interaction.error}</p></div>}</>
}
