import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { SessionProvider } from './workspace/Session'
import { Workspace } from './workspace/Workspace'
import { AgentBuilder, AgentProfile, AgentRegistry, MyAgents } from './workspace/Agents'
import { Publications, PublicationDetails } from './workspace/Publications'
import { Conversations, ConversationDetails, Inbox } from './workspace/Conversations'
import { CompanyDashboard, CompanyNotifications } from './workspace/Reporting'
import { PermissionGate } from './workspace/Permissions'
function gated(permission: string | string[], page: React.ReactNode) { return <PermissionGate permission={permission}>{page}</PermissionGate> }
export default function App() {
  return <BrowserRouter><SessionProvider><Routes><Route element={<AppLayout />}>
    <Route index element={<Workspace />} />
    <Route path="agents" element={gated('agents.read', <MyAgents />)} />
    <Route path="agents/new" element={gated('agents.manage', <AgentBuilder />)} />
    <Route path="agents/:agentId/edit" element={gated('agents.manage', <AgentBuilder />)} />
    <Route path="agents/:agentId" element={gated('agents.read', <AgentProfile />)} />
    <Route path="registry" element={gated('discovery.read', <AgentRegistry />)} />
    <Route path="feed" element={gated('posts.read', <Publications />)} />
    <Route path="publications/:publicationId" element={gated('posts.read', <PublicationDetails />)} />
    <Route path="notifications" element={<CompanyNotifications />} />
    <Route path="conversations" element={gated('conversations.read', <Conversations />)} />
    <Route path="conversations/invitations" element={gated('conversations.read', <Inbox />)} />
    <Route path="conversations/:conversationId" element={gated('conversations.read', <ConversationDetails />)} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes></SessionProvider></BrowserRouter>
}
