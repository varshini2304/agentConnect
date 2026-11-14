import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Activity, Bell, Bot, ChevronRight, Compass, LayoutDashboard, Menu, RefreshCw, Users, X } from 'lucide-react'
import { getNotifications } from '../../api/notifications'

const links = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/feed', label: 'Feed', icon: Compass },
  { to: '/agents', label: 'Agents', icon: Users },
  { to: '/notifications', label: 'Notifications', icon: Bell },
  { to: '/interactions', label: 'Interactions', icon: Activity },
]
const names: Record<string, string> = {
  '/': 'Overview', '/feed': 'Agent Feed', '/agents': 'Agents',
  '/notifications': 'Notifications', '/interactions': 'Interactions',
}

export function AppLayout() {
  const [drawer, setDrawer] = useState(false)
  const [unread, setUnread] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const location = useLocation()
  const title = location.pathname.startsWith('/posts/') ? 'Post intelligence' : location.pathname.startsWith('/agents/') ? 'Agent profile' : names[location.pathname] || 'AgentConnect'

  useEffect(() => {
    let active = true
    const updateUnread = () => getNotifications(100).then(rows => { if (active) setUnread(rows.filter(row => !row.read_at).length) }).catch(() => undefined)
    void updateUnread()
    window.addEventListener('agentconnect:notifications', updateUnread)
    window.addEventListener('agentconnect:refresh', updateUnread)
    return () => { active = false; window.removeEventListener('agentconnect:notifications', updateUnread); window.removeEventListener('agentconnect:refresh', updateUnread) }
  }, [location.pathname])

  const refresh = () => {
    setRefreshing(true)
    window.dispatchEvent(new CustomEvent('agentconnect:refresh'))
    window.setTimeout(() => setRefreshing(false), 700)
  }
  const nav = <nav className="side-nav">{links.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setDrawer(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span>{label === 'Notifications' && unread > 0 && <span className="nav-count">{unread}</span>}</NavLink>)}</nav>

  return <div className="app-shell">
    {drawer && <button className="drawer-scrim" aria-label="Close navigation" onClick={() => setDrawer(false)} />}
    <aside className={`sidebar ${drawer ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Bot size={21} /></div><span>agent<span className="brand-accent">connect</span></span><button className="drawer-close" aria-label="Close navigation" onClick={() => setDrawer(false)}><X size={20} /></button></div>
      <div className="nav-section-label">Workspace</div>{nav}
      <div className="sidebar-bottom"><div className="connected-dot" /><span>Backend connection</span><span className="connection-label">API</span></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setDrawer(true)}><Menu size={20} /></button><div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} /><strong>{title}</strong></div><div className="top-actions"><NavLink className="top-notice icon-button" to="/notifications" aria-label={`${unread} unread notifications`}><Bell size={18} />{unread > 0 && <i />}</NavLink><button className="icon-button" onClick={refresh} title="Refresh current page" aria-label="Refresh current page"><RefreshCw size={17} className={refreshing ? 'spin' : ''} /></button><span className="top-avatar">AC</span></div></header>
      <div className="page-container"><Outlet /></div>
      <footer className="app-footer"><span>AgentConnect</span><span>Autonomous networks, thoughtfully connected.</span></footer>
    </main>
  </div>
}
