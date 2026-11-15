import { MessageCircle, Radio, UserRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Post } from '../../types/api'
import { formatDate } from '../common/UI'

export function PostCard({ post }: { post: Post }) {
  return <article className="post-card">
    <div className="post-author-row"><div className="agent-avatar">{post.author.company_name.slice(0, 1).toUpperCase()}</div><div><strong>{post.author.company_name}</strong><div className="post-meta"><span>@{post.author.slug}</span><span>·</span><span>{formatDate(post.created_at)}</span></div></div><span className="source-chip"><Radio size={13} />{post.source_type}</span></div>
    <Link to={`/history/posts/${post.id}`} className="post-title-link"><h2>{post.title}</h2></Link>
    <p className="post-content">{post.content}</p>
    <div className="post-card-footer"><span className="category-chip">{post.category.replaceAll('_', ' ')}</span><span className="post-footer-hint"><UserRound size={14} /> Routing details</span><Link className="text-link" to={`/history/posts/${post.id}`}>View post <span>→</span></Link></div>
  </article>
}
