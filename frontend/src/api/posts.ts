import { api, expectRecord } from './client'
import type { DemoResponse, Post, PostCreate, PostDetail, PostFeed } from '../types/api'

const validPostSummary = (post: any) => !!post && typeof post.id === 'number' && typeof post.title === 'string' && !!post.author && typeof post.author.company_name === 'string'
const validRouting = (row: any) => !!row && typeof row.id === 'number' && !!row.reason_json && typeof row.reason_json.agent_name === 'string' && Array.isArray(row.reason_json.matched_categories) && Array.isArray(row.reason_json.matched_keywords) && typeof row.reason_json.explanation === 'string'
const validInteraction = (row: any) => !!row && typeof row.id === 'number' && typeof row.status === 'string' && (row.comment == null || typeof row.comment.content === 'string')
export const getPosts = async (limit = 20, offset = 0) => expectRecord<PostFeed>((await api.get('/posts', { params: { limit, offset } })).data, row => Array.isArray(row.items) && typeof row.limit === 'number' && typeof row.offset === 'number' && row.items.every(validPostSummary), 'post feed')
export const getPost = async (id: number) => expectRecord<PostDetail>((await api.get(`/posts/${id}`)).data, row => validPostSummary(row) && Array.isArray(row.routing_decisions) && row.routing_decisions.every(validRouting) && Array.isArray(row.notifications) && row.notifications.every((item: any) => !!item.reason_json && typeof item.reason_json.explanation === 'string') && Array.isArray(row.interactions) && row.interactions.every(validInteraction) && Array.isArray(row.comments), 'post detail')
export const publishPost = async (post: PostCreate) => {
  const response = await api.post<Post>('/posts', post)
  const saved = expectRecord<Post>(response.data, validPostSummary, 'published post')
  return { post: saved, created: response.status === 201 }
}
export const runDemo = async (scenario_id = 'swiggy-diwali-promotion') => expectRecord<DemoResponse>((await api.post('/demo/run', { scenario_id })).data, row => typeof row.scenario_id === 'string' && typeof row.created === 'boolean' && !!row.post && typeof (row.post as PostDetail).id === 'number', 'demo workflow')
