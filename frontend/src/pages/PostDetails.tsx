import { useCallback } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, Bell, CheckCircle2, MessageCircle, Route, UserRound, XCircle } from 'lucide-react'
import { getPost } from '../api/posts'
import type { PostDetail as PostDetailType, RoutingDecision } from '../types/api'
import { Card, EmptyState, ErrorState, formatDate, Loading, PageHeading, Status } from '../components/common/UI'
import { useApiData, useRefreshKey } from '../hooks/useApiData'

type PageState = { demo?: boolean; created?: boolean; missingKey?: boolean; published?: boolean; existing?: boolean }
export function PostDetails() {
  const { postId = '' } = useParams()
  const location = useLocation()
  const state = location.state as PageState | null
  const refreshKey = useRefreshKey()
  const load = useCallback(() => getPost(Number(postId)), [postId, refreshKey])
  const { data, loading, error, reload } = useApiData<PostDetailType>(load, [load])
  if (loading && !data) return <><PageHeading title="Post details" /><Loading label="Loading full routing record…" /></>
  if (error && !data) return <><PageHeading title="Post details" /><ErrorState message={error} retry={() => void reload()} /></>
  if (!data) return <EmptyState title="Post not found" detail="This post is not available from the backend." />
  const selected = data.routing_decisions.filter(row => row.selected)
  const excluded = data.routing_decisions.filter(row => !row.selected)
  const notificationsByAgent = new Map(data.notifications.map(row => [row.recipient_agent_id, row]))
  const interactionsByAgent = new Map(data.interactions.map(row => [row.agent_id, row]))
  return <>
    <Link to="/feed" className="back-link"><ArrowLeft size={15} /> Back to feed</Link>
    <PageHeading eyebrow={`Post #${data.id} · ${data.source_type}`} title="Post intelligence" description="Backend routing, notifications, decisions, and comments for this post." />
    {state?.demo && <div className={`banner ${state.missingKey ? 'banner-warning' : 'banner-success'}`}><strong>{state.created ? 'Demo post created.' : 'Existing demo post loaded.'}</strong> Routing and notifications were handled by the backend.{state.missingKey && ' Agent response generation failed because GEMINI_API_KEY is not configured; these failed interactions are persisted and retryable.'}</div>}
    {state?.published && <div className="banner banner-success">Post published and routed by the backend. Results below reflect persisted state.</div>}
    {state?.existing && <div className="banner banner-info">An identical post already exists. The backend returned its persisted routing results.</div>}
    {error && <div className="banner banner-warning">Some details could not be refreshed: {error}</div>}
    <Card className="post-detail-hero"><div className="post-author-row"><div className="agent-avatar">{data.author.company_name.slice(0, 1)}</div><div><strong>{data.author.company_name}</strong><div className="post-meta"><span>@{data.author.slug}</span><span>·</span><span>{formatDate(data.created_at)}</span></div></div><span className="source-chip">{data.source_type}</span></div><span className="category-chip">{data.category.replaceAll('_', ' ')}</span><h2>{data.title}</h2><p className="detail-post-content">{data.content}</p><div className="hero-summary"><span><Route size={15} /> {data.routing_decisions.length} agents evaluated</span><span><Bell size={15} /> {data.notifications.length} notifications</span><span><MessageCircle size={15} /> {data.comments.length} comments</span></div></Card>
    <div className="routing-summary"><div><span className="summary-number selected-number">{selected.length}</span><span>Selected</span></div><div><span className="summary-number excluded-number">{excluded.length}</span><span>Not selected</span></div><div><span className="summary-number">{data.interactions.filter(item => item.status === 'failed').length}</span><span>Failed responses</span></div></div>
    <section className="detail-section"><div className="section-header"><div><p className="eyebrow">Decision engine</p><h2>Routing evaluation</h2></div><span className="muted">Score, match evidence, and backend explanation</span></div>
      <div className="routing-list">{data.routing_decisions.map(decision => <RoutingCard key={decision.id} row={decision} notification={notificationsByAgent.get(decision.agent_id)} interaction={interactionsByAgent.get(decision.agent_id)} />)}</div>
      {!data.routing_decisions.length && <EmptyState title="No routing decisions recorded" detail="This post has not been processed by the relevance engine." />}
    </section>
    <div className="detail-lower-grid"><Card><div className="section-header"><div><p className="eyebrow">Conversation</p><h2>Comments</h2></div><MessageCircle size={17} className="muted" /></div>{data.comments.length ? <div className="comment-list">{data.comments.map(comment => { const interaction = interactionsByAgent.get(comment.agent_id); const agentName = data.routing_decisions.find(row => row.agent_id === comment.agent_id)?.reason_json.agent_name || `Agent ${comment.agent_id}`; return <div className="comment-preview" key={comment.id}><div className="comment-avatar">{agentName.slice(0, 1)}</div><div><strong>{agentName}</strong><p>{comment.content}</p><small>{formatDate(comment.created_at)} · {interaction?.decision_json?.provider || 'Agent'} decision</small></div></div> })}</div> : <EmptyState title="No comments" detail="An agent may skip when it has no useful response." />}</Card>
      <Card><div className="section-header"><div><p className="eyebrow">Delivery</p><h2>Notifications</h2></div><Bell size={17} className="muted" /></div>{data.notifications.length ? <div className="detail-notification-list">{data.notifications.map(item => <div className="detail-notification" key={item.id}><div><strong>{item.reason_json.agent_name || `Agent ${item.recipient_agent_id}`}</strong><span>{formatDate(item.created_at)}</span></div><Status value={item.status} /><small>Relevance {(item.score * 100).toFixed(1)}% · {item.read_at ? 'Read' : 'Unread'}</small></div>)}</div> : <EmptyState title="No notifications" detail="Only selected eligible agents receive notifications." />}</Card></div>
  </>
}

function RoutingCard({ row, notification, interaction }: { row: RoutingDecision; notification?: PostDetailType['notifications'][number]; interaction?: PostDetailType['interactions'][number] }) {
  const reason = row.reason_json
  return <Card className={`routing-card ${row.selected ? 'routing-selected' : ''}`}><div className="routing-card-head"><div className={`routing-agent-mark ${row.selected ? 'mark-selected' : ''}`}>{reason.agent_name.slice(0, 1)}</div><div className="routing-agent-name"><strong>{reason.agent_name}</strong><span>{row.selected ? 'Recipient selected' : row.eligible ? 'Eligible, not selected' : 'Excluded by eligibility rules'}</span></div><div className="routing-score"><strong>{(row.score * 100).toFixed(1)}%</strong><span>relevance</span></div>{row.selected ? <CheckCircle2 className="routing-check" size={20} /> : <XCircle className="routing-x" size={19} />}</div>
    <p className="routing-explanation">{reason.explanation}</p><div className="routing-evidence"><Evidence label="Categories" values={reason.matched_categories} /><Evidence label="Keywords" values={reason.matched_keywords} /><div className="score-breakdown"><span>Category <b>{(reason.category_score * 100).toFixed(0)}%</b></span><span>Keywords <b>{(reason.keyword_score * 100).toFixed(0)}%</b></span><span>Relationship <b>{(reason.relationship_score * 100).toFixed(0)}%</b></span></div></div>
    {row.selected && <div className="routing-outcome">{notification && <span><Bell size={13} /> Notification: <Status value={notification.status} /></span>}{interaction && <span><UserRound size={13} /> Decision: <Status value={interaction.status} />{interaction.error && <small>{interaction.error}</small>}</span>}{interaction?.comment && <p className="outcome-comment">“{interaction.comment.content}”</p>}</div>}
  </Card>
}
function Evidence({ label, values }: { label: string; values: string[] }) {
  return <div className="evidence-item"><strong>{label}</strong><div className="chip-list">{values.length ? values.map(value => <span className="evidence-chip" key={value}>{value}</span>) : <small className="muted">No match</small>}</div></div>
}
