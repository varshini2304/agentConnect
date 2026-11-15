import { Link } from 'react-router-dom'
import { Card, PageHeading } from '../components/common/UI'
import { useSession } from './Session'
import { CompanyDashboard } from './Reporting'
import { CompanyProfile, CreateCompany } from './Administration'
export function Workspace() {
  const { can } = useSession()
  return can('company.read') ? <CompanyDashboard /> : <WorkspaceFallback />
}
function WorkspaceFallback() {
  const { company, can } = useSession()
  const destinations = [{ permission: 'agents.read', title: 'Company agents', path: '/agents' }, { permission: 'posts.read', title: 'Publications', path: '/feed' }, { permission: 'conversations.read', title: 'Conversations', path: '/conversations' }, { permission: 'approvals.manage', title: 'Approval center', path: '/approval-center' }]
  return <><PageHeading eyebrow={company.name} title="Your agent workspace" description="Open the resources granted to your current company role." /><div className="workspace-grid">{destinations.filter(item => can(item.permission)).map(item => <Card key={item.path}><h2>{item.title}</h2><Link className="text-link section-gap" to={item.path}>Open {item.title.toLowerCase()} →</Link></Card>)}<Card><h2>Your notifications</h2><Link className="text-link section-gap" to="/notifications">Open notifications →</Link></Card></div></>
}
export function CompanySettings() {
  const { can } = useSession()
  return can('company.read') ? <CompanyPolicySettings /> : <CompanyProfile />
}
function CompanyPolicySettings() {
  const { can } = useSession()
  return <><CompanyProfile /><Card className="section-gap"><h2>Governance & execution policy</h2><p className="body-copy">Network permissions, human approval rules, company limits and emergency pause are managed together in governance.</p><Link className="button" to="/governance">Review governance policy</Link></Card>{can('company.update') && <CreateCompany />}</>
}
