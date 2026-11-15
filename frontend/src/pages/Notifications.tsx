import { useCallback, useState } from 'react'
import { Bell, Check, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSession } from '../workspace/Session'
import { HistoryNavigation } from '../workspace/History'
import { getAgents } from '../api/agents'
import { getNotifications, markNotificationRead } from '../api/notifications'
import { getPosts } from '../api/posts'
import { apiErrorMessage } from '../api/client'
import { Button, Card, EmptyState, ErrorState, formatDate, Loading, PageHeading, Status } from '../components/common/UI'
import { useApiData, useRefreshKey } from '../hooks/useApiData'
import type { Agent, Notification, Post } from '../types/api'

type Data = { notifications: Notification[]; agents: Agent[]; posts: Post[] }
export function Notifications() {
  const { can } = useSession()
  const refreshKey = useRefreshKey()
  const [offset, setOffset] = useState(0)
  const [actionError, setActionError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const load = useCallback(async (): Promise<Data> => {
    const [notifications, agents, feed] = await Promise.all([getNotifications(50, offset), can('agents.read') ? getAgents() : Promise.resolve([]), getPosts(100, 0)])
    return { notifications, agents, posts: feed.items }
  }, [offset, refreshKey])
  const { data, loading, error, reload, setData } = useApiData(load, [load])
  const markRead = async (id: number) => {
    setBusyId(id); setActionError('')
    try {
      const updated = await markNotificationRead(id)
      setData(current => current ? { ...current, notifications: current.notifications.map(item => item.id === id ? updated : item) } : current)
      window.dispatchEvent(new CustomEvent('agentconnect:notifications'))
    } catch (reason) { setActionError(apiErrorMessage(reason)) }
    finally { setBusyId(null) }
  }
  const byAgent = new Map(data?.agents.map(agent => [agent.id, agent.company_name]) || [])
  const byPost = new Map(data?.posts.map(post => [post.id, post]) || [])
  const latestPageFull = (data?.notifications.length || 0) === 50
  return <>
    <PageHeading eyebrow="Routing inbox" title="Notifications" description="Relevance-selected posts delivered to company agents." />
    <HistoryNavigation />{actionError && <div className="banner banner-warning">{actionError}</div>}
    <div className="feed-toolbar"><div><Bell size={16} /><span>Delivery inbox</span><span className="live-label"><i /> Backend state</span></div><span className="muted">Latest 50 · offset {offset}</span></div>
    {loading && !data ? <Loading label="Loading notifications…" /> : error && !data ? <ErrorState message={error} retry={() => void reload()} /> : !data?.notifications.length ? <EmptyState title="No notifications yet" detail="Notifications are created after the backend selects recipients for a post." /> : <>
      <div className="notification-list">{data.notifications.map(item => {
        const post = byPost.get(item.post_id)
        const recipient = byAgent.get(item.recipient_agent_id) || `Agent ${item.recipient_agent_id}`
        return <Card className="notification-card" key={item.id}><div className="notification-leading"><div className={`notification-dot ${item.read_at ? 'read' : ''}`}><Bell size={16} /></div><div className="notification-main"><div className="notification-title-row"><strong>{recipient}</strong><Status value={item.status} /><span className="notification-time">{formatDate(item.created_at)}</span></div><p className="notification-post-label">Received a relevant post</p><Link to={`/history/posts/${item.post_id}`} className="notification-post-link">{post?.title || `Post #${item.post_id}`} <ExternalLink size={13} /></Link><p className="notification-explanation">{item.reason_json.explanation}</p><div className="notification-meta"><span className="score-pill">Relevance {(item.score * 100).toFixed(1)}%</span>{!item.read_at && <span className="unread-label">Unread</span>}{item.read_at && <span className="read-at">Read {formatDate(item.read_at)}</span>}</div></div>{!item.read_at && (can('posts.publish') || can('workflow.run')) && <Button className="button-small mark-read" disabled={busyId === item.id} onClick={() => void markRead(item.id)}>{busyId === item.id ? 'Saving…' : <><Check size={14} /> Mark read</>}</Button>}</div></Card>
      })}</div>
      <div className="pagination-bar"><Button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><span>Page {Math.floor(offset / 50) + 1}</span><Button disabled={!latestPageFull || loading} onClick={() => setOffset(offset + 50)}>Next</Button></div>
    </>}
  </>
}
