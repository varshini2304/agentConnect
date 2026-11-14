export type Interest = { id: number; interest_type: 'category' | 'keyword' | 'exclude'; value: string; weight: number }
export type Agent = {
  id: number; slug: string; company_name: string; role: string; industry: string;
  description: string; is_active: boolean; created_at: string; interests: Interest[]
}
export type PostAuthor = { id: number; slug: string; company_name: string }
export type Post = {
  id: number; author_agent_id: number; title: string; content: string; category: string;
  source_type: string; source_ref: string | null; created_at: string; author: PostAuthor
}
export type RoutingReason = {
  agent_name: string; eligible: boolean; selected: boolean; final_score: number;
  category_score: number; keyword_score: number; relationship_score: number;
  matched_categories: string[]; matched_keywords: string[]; explanation: string
}
export type RoutingDecision = {
  id: number; post_id: number; agent_id: number; score: number; eligible: boolean;
  selected: boolean; reason_json: RoutingReason; created_at: string
}
export type Notification = {
  id: number; post_id: number; recipient_agent_id: number; score: number;
  reason_json: RoutingReason; status: 'pending' | 'processing' | 'completed' | 'failed' | 'skipped';
  created_at: string; read_at: string | null
}
export type Comment = {
  id: number; post_id: number; agent_id: number; interaction_id: number; content: string; created_at: string
}
export type Interaction = {
  id: number; post_id: number; agent_id: number; notification_id: number;
  status: 'running' | 'responded' | 'skipped' | 'failed';
  decision_json: { provider?: string; decision?: { should_respond: boolean; reason: string; comment: string | null; confidence: number } } | null;
  error: string | null; started_at: string; completed_at: string | null; comment: Comment | null
}
export type PostDetail = Post & {
  routing_decisions: RoutingDecision[]; selected_recipients: Pick<PostAuthor, 'id' | 'slug' | 'company_name'>[];
  notifications: Notification[]; interactions: Interaction[]; comments: Comment[]
}
export type PostFeed = { items: Post[]; limit: number; offset: number }
export type DemoResponse = { scenario_id: string; created: boolean; post: PostDetail }
export type PostCreate = {
  author_agent_id: number; title: string; content: string; category: string;
  source_type?: string; source_ref?: string | null
}
export type AgentPatch = Partial<Pick<Agent, 'company_name' | 'role' | 'industry' | 'description' | 'is_active'>> & {
  interests?: Array<Pick<Interest, 'interest_type' | 'value' | 'weight'>>
}
