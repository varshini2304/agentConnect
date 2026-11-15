import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { SessionProvider } from './workspace/Session'
import { Workspace, CompanySettings } from './workspace/Workspace'
import { AgentBuilder, AgentProfile, AgentRegistry, MyAgents } from './workspace/Agents'
import { Publications, PublicationDetails } from './workspace/Publications'
import { Conversations, ConversationDetails, Inbox } from './workspace/Conversations'
import { HistoricalDashboard } from './workspace/History'
import { Feed } from './pages/Feed'
import { PostDetails } from './pages/PostDetails'
import { Notifications } from './pages/Notifications'
import { Interactions } from './pages/Interactions'
import { Agents } from './pages/Agents'
import { AgentDetails } from './pages/AgentDetails'
import { Governance, ApprovalCenter, ApprovalDetails } from './workspace/Governance'
import { AgentActivityPage, Analytics, Audit, CompanyNotifications } from './workspace/Reporting'
import { PermissionGate } from './workspace/Access'
import { Account, CompanyProfile, CompanyInvitations, Roles, Team } from './workspace/Administration'
function gated(permission: string | string[], page: React.ReactNode) { return <PermissionGate permission={permission}>{page}</PermissionGate> }
export default function App() {
  return <BrowserRouter><SessionProvider><Routes><Route element={<AppLayout />}>
    <Route index element={<Workspace />} /><Route path="agents" element={gated('agents.read', <MyAgents />)} /><Route path="agents/new" element={gated('agents.manage', <AgentBuilder />)} /><Route path="agents/:agentId/edit" element={gated('agents.manage', <AgentBuilder />)} /><Route path="agents/:agentId/activity" element={gated('agents.read', <AgentActivityPage />)} /><Route path="agents/:agentId" element={gated('agents.read', <AgentProfile />)} />
    <Route path="registry" element={gated('discovery.read', <AgentRegistry />)} /><Route path="feed" element={gated('posts.read', <Publications />)} /><Route path="publications/:publicationId" element={gated('posts.read', <PublicationDetails />)} />
    <Route path="conversations" element={gated('conversations.read', <Conversations />)} /><Route path="conversations/:conversationId" element={gated('conversations.read', <ConversationDetails />)} /><Route path="governance" element={gated('company.read', <Governance />)} /><Route path="approval-center" element={gated('approvals.manage', <ApprovalCenter />)} /><Route path="approval-center/:approvalId" element={gated('approvals.manage', <ApprovalDetails />)} /><Route path="notifications" element={<CompanyNotifications />} /><Route path="analytics" element={gated('company.read', <Analytics />)} /><Route path="audit" element={gated('settings.manage', <Audit />)} /><Route path="inbox" element={gated('conversations.read', <Inbox />)} /><Route path="settings" element={gated(['company.read', 'company.update', 'settings.manage'], <CompanySettings />)} /><Route path="history" element={gated('posts.read', <HistoricalDashboard />)} /><Route path="history/posts" element={gated('posts.read', <Feed />)} /><Route path="history/posts/:postId" element={gated('posts.read', <PostDetails />)} /><Route path="posts/:postId" element={gated('posts.read', <PostDetails />)} /><Route path="history/notifications" element={gated('posts.read', <Notifications />)} /><Route path="history/interactions" element={gated('posts.read', <Interactions />)} /><Route path="history/agents" element={gated('agents.read', <Agents />)} /><Route path="history/agents/:agentId" element={gated('agents.read', <AgentDetails />)} /><Route path="onboarding" element={gated('settings.manage', <CompanyProfile onboarding />)} /><Route path="team" element={gated('members.read', <Team />)} /><Route path="team/invitations" element={gated('invitations.manage', <CompanyInvitations />)} /><Route path="roles" element={gated('roles.read', <Roles />)} /><Route path="account" element={<Account />} /><Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes></SessionProvider></BrowserRouter>
}
