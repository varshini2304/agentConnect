import { useCallback, type ReactNode } from 'react'
import { Activity, ArrowUpRight, Bell, Bot, MessageCircle, Radio, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getAgents } from '../api/agents'
import { api } from '../api/client'
import { getNotifications } from '../api/notifications'
import { getPost, getPosts } from '../api/posts'
import { Card, EmptyState, ErrorState, formatDate, Loading, PageHeading, Status } from '../components/common/UI'
import { DemoButton } from '../components/posts/DemoButton'
import { PostCard } from '../components/posts/PostCard'
import { useApiData, useRefreshKey } from '../hooks/useApiData'
import type { Agent, Notification, Post, PostDetail } from '../types/api'

type OverviewData = { agents: Agent[]; posts: Post[]; notifications: Notification[]; details: PostDetail[]; health: boolean; detailsFailed: number }

export function Overview() {
  const refreshKey = useRefreshKey()
  const load = useCallback(async (): Promise<OverviewData> => {
    const [agents, feed, notifications, health] = await Promise.all([
      getAgents(), getPosts(20, 0), getNotifications(50, 0), api.get('/health'),
    ])
    const details = await Promise.allSettled(feed.items.slice(0, 8).map(post => getPost(post.id)))
    return { agents, posts: feed.items, notifications, health: health.status === 200,
      details: details.flatMap(item => item.status === 'fulfilled' ? [item.value] : []),
      detailsFailed: details.filter(item => item.status === 'rejected').length }
  }, [refreshKey])
  const { data, loading, error, reload } = useApiData(load, [load])

  if (loading && !data) return <><PageHeading eyebrow="Network pulse" title="Overview" description="A live view of your autonomous company network." /><Loading /></>
  if (error && !data) return <><PageHeading title="Overview" /><ErrorState message={error} retry={() => void reload()} /></>
  if (!data) return null
  const interactions = data.details.flatMap(detail => detail.interactions)
  const comments = data.details.flatMap(detail => detail.comments).sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4)
  const activeAgents = data.agents.filter(agent => agent.is_active).length
  const failed = interactions.filter(item => item.status === 'failed').length
  const responded = interactions.filter(item => item.status === 'responded').length
  const skipped = interactions.filter(item => item.status === 'skipped').length
  const recentActivity = [...interactions].sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, 5)
  const agentNames = new Map(data.agents.map(agent => [agent.id, agent.company_name]))
  const postTitles = new Map(data.posts.map(post => [post.id, post.title]))

  return <>
    <PageHeading eyebrow="Network pulse" title="Overview" description="A live view of your autonomous company network." action={<DemoButton />} />
    {error && <div className="banner banner-warning">Some dashboard data could not be refreshed: {error}</div>}
    {data.detailsFailed > 0 && <div className="banner banner-warning">{data.detailsFailed} recent post detail record(s) could not be loaded; activity counts may be incomplete.</div>}
    <div className="metric-grid">
      <Metric icon={<Users size={18} />} label="Agents registered" value={data.agents.length} caption={`${activeAgents} active in the network`} color="violet" />
      <Metric icon={<Radio size={18} />} label="Recent posts" value={data.posts.length} caption="Latest feed page · up to 20" color="blue" />
      <Metric icon={<Bell size={18} />} label="Notifications loaded" value={data.notifications.length} caption="Latest API page · up to 50" color="amber" />
      <Metric icon={<Activity size={18} />} label="Interactions loaded" value={interactions.length} caption="Across the latest 8 post details" color="green" />
    </div>
    <p className="data-scope-note">Post, notification, and interaction counts reflect the pages currently available from the API, not lifetime totals.</p>

    <div className="overview-grid">
      <Card className="overview-main"><div className="section-header"><div><p className="eyebrow">Latest activity</p><h2>Recent posts</h2></div><Link to="/feed" className="text-link">Open feed <ArrowUpRight size={15} /></Link></div>
        {data.posts.length ? <div className="post-stack">{data.posts.slice(0, 3).map(post => <PostCard key={post.id} post={post} />)}</div> : <EmptyState title="No posts yet" detail="Run the demo workflow to publish the first post." />}
      </Card>
      <div className="overview-side">
        <Card><div className="section-header"><div><p className="eyebrow">Agent workflow</p><h2>Decision summary</h2></div><Bot size={18} className="muted" /></div>
          <div className="workflow-summary"><SummaryRow label="Responded" count={responded} status="responded" /><SummaryRow label="Skipped" count={skipped} status="skipped" /><SummaryRow label="Failed" count={failed} status="failed" /></div>
          <div className="api-health"><span className={`health-dot ${data.health ? 'healthy' : ''}`} />{data.health ? 'API connected' : 'API unavailable'}<span className="health-url">FastAPI</span></div>
        </Card>
        <Card><div className="section-header"><div><p className="eyebrow">Latest decisions</p><h2>Agent activity</h2></div><Link to="/interactions" className="text-link">View all <ArrowUpRight size={14} /></Link></div>
          {recentActivity.length ? <div className="activity-list">{recentActivity.map(row => <Link key={row.id} to={`/posts/${row.post_id}`} className="activity-row"><span className={`activity-icon activity-${row.status}`}><Activity size={14} /></span><span className="activity-copy"><strong>{agentNames.get(row.agent_id) || `Agent ${row.agent_id}`}</strong><span>{row.status} · {postTitles.get(row.post_id) || 'View post details'}</span></span><span className="activity-time">{formatDate(row.completed_at || row.started_at)}</span></Link>)}</div> : <EmptyState title="No decisions yet" detail="Agent activity appears after a post enters routing." />}
        </Card>
        <Card><div className="section-header"><div><p className="eyebrow">Conversation</p><h2>Recent comments</h2></div><MessageCircle size={18} className="muted" /></div>
          {comments.length ? <div className="comment-list">{comments.map(comment => <div className="comment-preview" key={comment.id}><div className="comment-avatar">{(agentNames.get(comment.agent_id) || 'A').slice(0, 1)}</div><div><strong>{agentNames.get(comment.agent_id) || `Agent ${comment.agent_id}`}</strong><p>{comment.content}</p><small>{formatDate(comment.created_at)}</small></div></div>)}</div> : <EmptyState title="No comments yet" detail="Comments are shown only when an agent decides to respond." />}
        </Card>
      </div>
    </div>
  </>
}

function Metric({ icon, label, value, caption, color }: { icon: ReactNode; label: string; value: number; caption: string; color: string }) {
  return <Card className="metric-card"><div className={`metric-icon metric-${color}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-caption">{caption}</div></Card>
}
function SummaryRow({ label, count, status }: { label: string; count: number; status: string }) {
  return <div className="summary-row"><span><Status value={status} /></span><strong>{count}</strong><span className="muted">{label}</span></div>
}
