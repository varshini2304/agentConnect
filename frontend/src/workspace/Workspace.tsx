import { Link } from 'react-router-dom'
import { Card, PageHeading } from '../components/common/UI'
import { useSession } from './Session'
import { CompanyDashboard } from './Reporting'
export function Workspace() {
  const { can } = useSession()
  return can('company.read') ? <CompanyDashboard /> : <WorkspaceFallback />
}
function WorkspaceFallback() {
  const { company, can } = useSession()
  const destinations = [{ permission: 'agents.read', title: 'Company agents', path: '/agents' }, { permission: 'discovery.read', title: 'Agent registry', path: '/registry' }, { permission: 'posts.read', title: 'Publications', path: '/feed' }, { permission: 'conversations.read', title: 'Conversations', path: '/conversations' }]
  return <><PageHeading eyebrow={company.name} title="Your agent workspace" description="Open the resources granted to your current company role." /><div className="workspace-grid">{destinations.filter(item => can(item.permission)).map(item => <Card key={item.path}><h2>{item.title}</h2><Link className="text-link section-gap" to={item.path}>Open {item.title.toLowerCase()} →</Link></Card>)}<Card><h2>Your notifications</h2><Link className="text-link section-gap" to="/notifications">Open notifications →</Link></Card></div></>
}
