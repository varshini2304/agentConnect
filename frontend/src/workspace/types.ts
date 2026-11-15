export type Limits = { max_agent_messages: number; max_conversation_messages: number; max_reply_depth: number; max_participants: number; max_concurrent_runs: number; max_retries: number; timeout_seconds: number; cooldown_seconds: number; daily_runs: number }
export type CompanyPolicy = { allow_public: boolean; allow_direct: boolean; allow_group: boolean; allow_initiation: boolean; allow_invitations: boolean; allow_replies: boolean; allow_knowledge: boolean; allow_discovery: boolean; emergency_paused: boolean; allowed_actions: string[]; daily_execution_budget: number; excluded_topics: string[]; approval_categories: string[]; restricted_categories: string[]; require_invitation_approval: boolean; require_publish_approval: boolean; limits: Limits; blocked_company_ids: number[]; approval_topics: string[] }
export type CompanySettings = { description: string; website: string; industry: string; onboarding_complete: boolean }
export type Company = { id: number; name: string; slug: string; status: string; created_at: string; updated_at: string; network_opt_in: boolean; policy: CompanyPolicy; policy_version: number; role: string; role_id: number | null; permissions: string[]; settings: CompanySettings }
export type Session = { user: { id: number; email: string; name: string; status: string; created_at: string; last_login_at: string | null }; companies: Company[]; selected_company_id: number | null; csrf_token: string }
export type CompanyMember = { id: number; user_id: number; email: string; name: string; status: string; role: string; role_id: number | null; created_at: string }
export type CompanyRole = { id: number; name: string; slug: string; is_builtin: boolean; permissions: string[] }
export type Permission = { key: string; description: string }
export type CompanyInvitation = { id: number; email: string; role_id: number | null; role: string; status: string; expires_at: string; delivery?: 'development_link' | 'not_configured'; development_token?: string }
export type InvitationPreview = { company_name: string; email: string; expires_at: string; role: string }
export type Platform = { providers: Record<string, string[]>; limits: Partial<Limits> }
export type AgentConfig = {
  name: string; avatar: string; description: string; role: string; domain: string; purpose: string;
  responsibilities: string[]; helps_with: string[]; must_not_do: string[]; expected_outcomes: string[];
  categories: string[]; topics: string[]; keywords: string[]; excluded_topics: string[];
  partner_company_ids: number[]; blocked_company_ids: number[]; discoverable: boolean;
  tone: string; response_preferences: string; allow_public: boolean; allow_direct: boolean; allow_group: boolean;
  allow_initiation?: boolean; allow_invitations?: boolean; allow_replies?: boolean; allow_knowledge?: boolean; approval_categories?: string[];
  discussion_topics: string[]; approval_topics: string[]; allowed_actions: string[]; allowed_publishing_categories: string[];
  require_approval: boolean; limits: Limits; provider: string; model: string; temperature: number; max_output_tokens: number; knowledge_source_ids: number[];
}
export type ManagedAgent = { id: number; company_id: number; company_name: string; slug: string; state: string; active_version_id: number | null; config_version_id: number; config: AgentConfig; created_at: string }
export type PublicAgent = { id: number; company_id: number; company_name: string; slug: string; name: string; description: string; role: string; domain: string; avatar: string }
export type Version = { id: number; version: number; config: AgentConfig; created_at: string }
export type Knowledge = { id: number; name: string; visibility: 'private' | 'shareable'; source_url: string | null; created_at: string; content?: string }
export type KnowledgeInput = { name: string; content: string; visibility: 'private' | 'shareable'; source_url?: string }
export type Publication = { approval_request_id?: number | null; approval_status?: string | null; id: number; company_id: number; company_name: string; author_type: string; user_id: number | null; agent_id: number | null; title: string; content: string; category: string; visibility: string; status: string; config_version_id: number | null; policy_version: number; created_at: string }
export type Discovery = { agent_id: number; agent_name: string; company_id: number; eligible: boolean; selected: boolean; score: number; explanation: string; signals: Record<string, unknown> }
export type Member = { id: number; agent_id: number; agent_name: string; company_id: number; company_name: string; status: string; joined_at: string | null; left_at: string | null; history_from_seq: number; config_version_id: number }
export type Conversation = { id: number; kind: 'direct' | 'group'; title: string; status: string; created_at: string; members: Member[]; message_count: number }
export type Delivery = { id: number; agent_id: number; status: string; attempts: number; error: string | null }
export type Message = { id: number; conversation_id: number; sequence: number; sender_agent_id: number | null; sender_user_id: number | null; author_type: string; content: string; reply_depth: number; created_at: string; deliveries: Delivery[] }
export type Run = { id: number; agent_id: number; delivery_id: number; config_version_id: number; policy_version: number; status: string; action: string | null; reason: string | null; provider: string; model: string; created_at: string; attempts: { id: number; number: number; status: string; error: string | null; started_at: string; completed_at: string | null }[] }
export type Invitation = { id: number; conversation_id: number; inviter_agent_id: number; recipient_agent_id: number; status: string; requires_approval: boolean; created_at: string }
export type Approval = { id: number; conversation_id: number; agent_id: number; run_id: number; status: string; content: string | null; reason: string }

export type PublishingJob = { id: number; agent_id: number; title: string; category: string; status: string; attempts: number; error: string | null; publication_id: number | null; config_version_id: number; created_at: string }

export type PageResult<T> = { items: T[]; total: number; offset: number; limit: number }
export type Governance = { company_id: number; policy_version: number; network_opt_in: boolean; policy: CompanyPolicy }
export type GovernanceApproval = { decision?: string | null; id: number; company_id: number; agent_id: number | null; requesting_user_id: number | null; action_type: string; source_type: string; source_id: number; proposed_content: unknown; category: string; reason: string; triggered_policy: string[]; config_version_id: number | null; policy_version: number; status: string; reviewer_id: number | null; decision_at: string | null; reviewer_comments: string | null; expires_at: string; created_at: string }
export type AuditEvent = { id: number; company_id: number; actor_type: string; actor_id: number | null; event_type: string; resource_type: string; resource_id: number | null; outcome: string; metadata: Record<string, unknown>; created_at: string }
export type UserNotification = { conversation_id?: number; agent_id?: number; id: number; company_id: number; category: string; title: string; resource_type: string; resource_id: number | null; read_at: string | null; created_at: string }
export type Usage = { daily_runs: number; daily_budget: number; remaining: number }
export type CompanyDashboard = { agents: { total: number; active: number; paused: number }; published_posts: number; active_conversations: number; direct_conversations: number; group_conversations: number; pending_approvals: number; failed_executions: number; usage: Usage; recent_activity: AuditEvent[]; recent_notifications: UserNotification[] }
export type DailyAnalytics = { date: string; runs: number; messages: number; conversations: number; skips: number; approvals: number; retries: number }
export type CompanyAnalytics = { days: number; totals: { runs: number; messages: number; conversations: number; skips: number; approvals: number; retries: number; routing_evaluations: number; routing_selected: number; failed_executions: number }; daily: DailyAnalytics[]; agents: { agent_id: number; name: string; runs: number; messages: number; conversations: number; skips: number; failures: number }[]; usage: Usage }
export type AgentActivity = { agent_id: number; runs: (Partial<Run> & { id: number; status: string; conversation_id?: number })[]; messages: { id: number; conversation_id: number; sequence?: number; author_type?: string; created_at: string; content?: never }[]; conversations: { id: number; kind: string; status: string; created_at: string }[]; failures: (Partial<Run> & { id: number; status: string; error?: string | null; resource_type?: string; conversation_id?: number })[] }
