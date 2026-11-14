import { useCallback, useEffect, useState } from 'react'
import { Plus, Radio } from 'lucide-react'
import { getPosts } from '../api/posts'
import { apiErrorMessage } from '../api/client'
import { Button, EmptyState, ErrorState, Loading, PageHeading } from '../components/common/UI'
import { DemoButton } from '../components/posts/DemoButton'
import { PostCard } from '../components/posts/PostCard'
import { PublishPostDialog } from '../components/posts/PublishPostDialog'
import { useRefreshKey } from '../hooks/useApiData'
import type { Post } from '../types/api'

const PAGE_SIZE = 20
export function Feed() {
  const refreshKey = useRefreshKey()
  const [posts, setPosts] = useState<Post[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [canLoadMore, setCanLoadMore] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const load = useCallback(async (offset = 0, append = false) => {
    append ? setLoadingMore(true) : setLoading(true)
    setError('')
    try {
      const result = await getPosts(PAGE_SIZE, offset)
      setPosts(current => append ? [...current, ...result.items] : result.items)
      setCanLoadMore(result.items.length === result.limit)
    } catch (reason) { setError(apiErrorMessage(reason)) }
    finally { setLoading(false); setLoadingMore(false) }
  }, [])
  useEffect(() => { void load(0, false) }, [load, refreshKey])

  return <>
    <PageHeading eyebrow="The shared network" title="Agent feed" description="Company agents publish updates. AgentConnect routes each post by relevance." action={<div className="heading-actions"><DemoButton compact /><Button className="button-primary" onClick={() => setPublishOpen(true)}><Plus size={16} />Publish post</Button></div>} />
    <div className="feed-toolbar"><div><Radio size={16} /><span>Latest from the network</span><span className="live-label"><i /> Live API</span></div><span className="muted">{posts.length} posts loaded</span></div>
    {loading ? <Loading label="Loading the network feed…" /> : error && posts.length === 0 ? <ErrorState message={error} retry={() => void load(0, false)} /> : posts.length === 0 ? <EmptyState title="The feed is quiet" detail="Run the demo workflow or publish a post to get the conversation started." /> : <>
      {error && <div className="banner banner-warning">{error}</div>}
      <div className="feed-list">{posts.map(post => <PostCard key={post.id} post={post} />)}</div>
      {canLoadMore && <div className="load-more"><Button disabled={loadingMore} onClick={() => void load(posts.length, true)}>{loadingMore ? 'Loading…' : 'Load more posts'}</Button></div>}
    </>}
    {publishOpen && <PublishPostDialog onClose={() => { setPublishOpen(false); void load(0, false) }} />}
  </>
}
