import type { AgentConfig, CompanyPolicy, DailyAnalytics, Limits, Platform } from './types'
export const defaultLimits: Limits = { max_agent_messages: 3, max_conversation_messages: 12, max_reply_depth: 6, max_participants: 8, max_concurrent_runs: 2, max_retries: 3, timeout_seconds: 30, cooldown_seconds: 30, daily_runs: 100 }
export const limitFields: { key: keyof Limits; label: string; min: number; max: number; step?: number | 'any' }[] = [
  { key: 'max_agent_messages', label: 'Replies per agent', min: 0, max: 100 }, { key: 'max_conversation_messages', label: 'Conversation messages', min: 1, max: 1000 },
  { key: 'max_reply_depth', label: 'Reply depth', min: 0, max: 100 }, { key: 'max_participants', label: 'Participants', min: 2, max: 100 },
  { key: 'max_concurrent_runs', label: 'Concurrent runs', min: 1, max: 20 }, { key: 'max_retries', label: 'Retries', min: 0, max: 10 },
  { key: 'timeout_seconds', label: 'Timeout (seconds)', min: 0.05, max: 120, step: 'any' }, { key: 'cooldown_seconds', label: 'Cooldown (seconds)', min: 0, max: 86400, step: 'any' }, { key: 'daily_runs', label: 'Daily runs', min: 0, max: 10000 },
]
export function newConfig(platform: Platform): AgentConfig {
  const provider = Object.keys(platform.providers).find(key => platform.providers[key].length > 0) || ''
  return { name: '', avatar: '🤖', description: '', role: '', domain: '', purpose: '', responsibilities: [], helps_with: [], must_not_do: [], expected_outcomes: [], categories: [], topics: [], keywords: [], excluded_topics: [], partner_company_ids: [], blocked_company_ids: [], discoverable: true, tone: 'professional', response_preferences: 'concise', allow_public: false, allow_direct: true, allow_group: true, allow_initiation: true, allow_invitations: true, allow_replies: true, allow_knowledge: true, approval_categories: [], discussion_topics: [], approval_topics: [], allowed_actions: ['reply', 'skip', 'request_approval', 'end_conversation'], allowed_publishing_categories: [], require_approval: false, limits: { ...defaultLimits, ...platform.limits }, provider, model: platform.providers[provider]?.[0] || '', temperature: 0.2, max_output_tokens: 500, knowledge_source_ids: [] }
}
export function phrases(value: string): string[] { return [...new Set(value.split('\n').map(item => item.trim()).filter(Boolean))] }
export function companyIds(value: string): number[] {
  if (!value.trim()) return []
  const values = value.split(/[\s,]+/).filter(Boolean)
  if (values.some(item => !/^\d+$/.test(item) || !Number.isSafeInteger(Number(item)) || Number(item) < 1)) throw new Error('Company IDs must be positive whole numbers, separated by commas.')
  return [...new Set(values.map(Number))]
}
export function validateConfig(config: AgentConfig): string | null {
  if (['name', 'description', 'role', 'domain', 'purpose'].some(key => !String(config[key as keyof AgentConfig]).trim())) return 'Complete the name, description, role, domain and purpose before saving.'
  if (!config.provider || !config.model) return 'Select an available provider and model.'
  for (const field of limitFields) {
    const value = config.limits[field.key]
    if (!Number.isFinite(value) || value < field.min || value > field.max || (!field.step && !Number.isInteger(value))) return `Review the runtime limit: ${field.label}.`
  }
  if (!Number.isFinite(config.temperature) || config.temperature < 0 || config.temperature > 1) return 'Temperature must be between 0 and 1.'
  if (!Number.isInteger(config.max_output_tokens) || config.max_output_tokens < 64 || config.max_output_tokens > 2000) return 'Output tokens must be between 64 and 2000.'
  return null
}
export function requestKey(): string { return crypto.randomUUID() }
export async function readKnowledgeFile(file: File): Promise<string> {
  if (!/\.(txt|text|md|markdown|csv|json)$/i.test(file.name)) throw new Error('Choose a text, Markdown, CSV or JSON document.')
  if (file.size > 100 * 1024) throw new Error('Documents must be 100 KB or smaller.')
  const content = await file.text()
  if (!content.trim() || content.includes('\u0000')) throw new Error('The document must contain readable text.')
  return content
}

export const approvalCategories = ['general_information', 'product_announcement', 'promotional_offer', 'financial_claim', 'partnership_proposal', 'binding_commitment', 'external_action']
export const runtimeActions = ['reply', 'skip', 'request_approval', 'end_conversation']
export function normalizePolicy(value: Partial<CompanyPolicy>): CompanyPolicy {
  return { allow_public: true, allow_direct: true, allow_group: true, allow_initiation: true, allow_invitations: true, allow_replies: true, allow_knowledge: true, allow_discovery: true, emergency_paused: false, allowed_actions: [...runtimeActions], daily_execution_budget: 1000, excluded_topics: [], approval_categories: [], restricted_categories: [], require_invitation_approval: true, require_publish_approval: false, blocked_company_ids: [], approval_topics: [], ...value, limits: { ...defaultLimits, ...value.limits } }
}
// SQLite timestamps are UTC without an offset; PostgreSQL returns an explicit offset.
export function parseApiDate(value: string): number { return Date.parse(/(?:[zZ]|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`) }
export function canReviewApproval(status: string, expiresAt: string, now = Date.now()): boolean { const expires = parseApiDate(expiresAt); return status === 'pending' && Number.isFinite(expires) && expires > now }
export function trendPoints(rows: DailyAnalytics[], metric: keyof Omit<DailyAnalytics, 'date'>): string {
  const max = Math.max(1, ...rows.map(row => row[metric]))
  return rows.map((row, index) => `${rows.length < 2 ? 50 : index * 100 / (rows.length - 1)},${100 - row[metric] * 90 / max}`).join(' ')
}
