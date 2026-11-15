import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Bot, ChevronRight, Compass, Menu, MessageSquare, Settings, Users, X, Inbox, LayoutDashboard, LogOut, Shield, UserRound, History, Bell, BarChart3, CheckCircle2, FileText } from 'lucide-react'
import { logout, switchCompany, useSession } from '../../workspace/Session'
import { Button } from '../common/UI'
import { useAction } from '../../workspace/common'
const links = [
  { to: '/', label: 'Company dashboard', icon: LayoutDashboard, permission: '', end: true },
  { to: '/agents', label: 'My agents', icon: Bot, permission: 'agents.read' },
  { to: '/registry', label: 'Agent registry', icon: Users, permission: 'discovery.read' },
  { to: '/feed', label: 'Publications', icon: Compass, permission: 'posts.read' },
  { to: '/conversations', label: 'Conversations', icon: MessageSquare, permission: 'conversations.read' },
  { to: '/inbox', label: 'Conversation invitations', icon: Inbox, permission: 'conversations.read' },
  { to: '/approval-center', label: 'Approval center', icon: CheckCircle2, permission: 'approvals.manage' },
  { to: '/notifications', label: 'Notifications', icon: Bell, permission: '' },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, permission: 'company.read' },
  { to: '/governance', label: 'Governance', icon: Shield, permission: 'company.read' },
  { to: '/audit', label: 'Audit log', icon: FileText, permission: 'settings.manage' },
  { to: '/history', label: 'Historical activity', icon: History, permission: 'posts.read' },
  { to: '/team', label: 'Company team', icon: Users, permission: 'members.read', end: true },
  { to: '/team/invitations', label: 'Company invitations', icon: Inbox, permission: 'invitations.manage' },
  { to: '/roles', label: 'Roles & permissions', icon: Shield, permission: 'roles.read' },
  { to: '/settings', label: 'Company settings', icon: Settings, permission: ['company.read', 'company.update', 'settings.manage'] },
  { to: '/account', label: 'My account', icon: UserRound, permission: '' },
]
export function AppLayout() {
  const { session, company, can } = useSession()
  const action = useAction()
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  const title = links.find(link => link.to !== '/' && location.pathname.startsWith(link.to))?.label || 'Workspace'
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    {drawer && <button className="drawer-scrim" aria-label="Close navigation" onClick={() => setDrawer(false)} />}
    <aside className={`sidebar ${drawer ? 'sidebar-open' : ''}`}><div className="brand"><div className="brand-mark"><Bot size={21} /></div><span>agent<span className="brand-accent">connect</span></span><button className="drawer-close" aria-label="Close navigation" onClick={() => setDrawer(false)}><X size={20} /></button></div>
      <label className="workspace-select">Company workspace<select value={company.id} disabled={action.busy} onChange={event => void action.run(() => switchCompany(Number(event.target.value)))}>{session.companies.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <nav className="side-nav" aria-label="Main navigation">{links.filter(link => !link.permission || (Array.isArray(link.permission) ? link.permission.some(can) : can(link.permission))).map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setDrawer(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><span>{session.user.name}</span><Button aria-label="Sign out" className="button-small" disabled={action.busy} onClick={() => void action.run(() => logout())}><LogOut size={14} />Sign out</Button></div>
    </aside>
    <main className="main-shell"><header className="topbar"><button className="mobile-menu icon-button" aria-label="Open navigation" aria-expanded={drawer} onClick={() => setDrawer(true)}><Menu size={20} /></button><div className="breadcrumbs"><span>{company.name}</span><ChevronRight size={14} /><strong>{title}</strong></div><div className="top-actions"><span className="workspace-role">{company.role}</span><span className="top-avatar">{session.user.name.slice(0, 2).toUpperCase()}</span></div></header><div id="main-content" tabIndex={-1} className="page-container">{action.error && <p role="alert" className="form-error">{action.error}</p>}<Outlet /></div><footer className="app-footer"><span>AgentConnect</span><span>{company.network_opt_in ? 'Network enabled' : 'Company workspace'} · Policy v{company.policy_version}</span></footer></main>
  </div>
}
