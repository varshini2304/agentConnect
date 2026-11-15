import { Link, NavLink } from 'react-router-dom'
import { Card, PageHeading } from '../components/common/UI'
import { PostCard } from '../components/posts/PostCard'
import { DemoButton } from '../components/posts/DemoButton'
import { getPosts } from '../api/posts'
import { get } from './api'
import { NoRows, Resource, useResource } from './common'
import { useSession } from './Session'
export type DashboardCounts = { agents: number; posts: number; notifications: number; interactions: number; unread_notifications: number; failed_interactions: number }
export function HistoryNavigation() { const { can } = useSession(); return <nav className="filter-tabs history-nav" aria-label="Historical activity"><NavLink className="button" to="/history" end>Overview</NavLink><NavLink className="button" to="/history/posts">Posts</NavLink><NavLink className="button" to="/history/notifications">Notifications</NavLink><NavLink className="button" to="/history/interactions">Interactions</NavLink>{can('agents.read') && <NavLink className="button" to="/history/agents">Agent profiles</NavLink>}</nav> }
export function HistoricalDashboard() {
  const { can } = useSession()
  const resource = useResource(async () => { const [counts, feed] = await Promise.all([can('company.read') ? get<DashboardCounts>('/dashboard') : Promise.resolve(null), getPosts(5, 0)]); return { counts, feed } })
  return <><PageHeading eyebrow="Preserved company activity" title="Historical activity" description="Your company’s original posts, routing decisions, notifications and agent responses. Records retain their existing identities." action={can('posts.publish') && can('workflow.run') && <DemoButton />} /><HistoryNavigation /><Resource resource={resource}>{data => <>{data.counts && <div className="metric-grid">{[{ label: 'Historical posts', value: data.counts.posts, to: '/history/posts' }, { label: 'Unread notifications', value: data.counts.unread_notifications, to: '/history/notifications' }, { label: 'Agent interactions', value: data.counts.interactions, to: '/history/interactions' }, { label: 'Failed interactions', value: data.counts.failed_interactions, to: '/history/interactions' }].map(item => <Link to={item.to} key={item.label}><Card className="metric-card"><p className="metric-label">{item.label}</p><div className="metric-value">{item.value}</div></Card></Link>)}</div>}<div className="feed-list section-gap">{data.feed.items.length ? data.feed.items.map(post => <PostCard post={post} key={post.id} />) : <NoRows title="No historical posts" detail="This company has no preserved posts yet. Authorized teammates can publish or run an available demonstration." />}</div></>}</Resource></>
}
