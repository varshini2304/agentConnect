import type { Company, Session } from './types'
export function hasPermission(company: Pick<Company, 'status' | 'permissions'> | null | undefined, permission: string): boolean {
  return company?.status === 'active' && company.permissions.includes(permission)
}
export function selectedCompany(session: Session): Company | undefined { return session.companies.find(company => company.id === session.selected_company_id && company.status === 'active') }
export function companyScopeFor(path: string, companyId: number | null): number | null {
  const resource = path.split('?')[0]
  if (!companyId || !Number.isSafeInteger(companyId) || companyId < 1 || /^\/(auth|account)(\/|$)/.test(resource) || /^\/company-invitations\/(preview|accept)$/.test(resource)) return null
  return companyId
}
export function csrfCookie(cookies: string): string | null {
  const entries = cookies.split(';').map(value => value.trim())
  for (const name of ['__Host-agentconnect_csrf', 'agentconnect_csrf']) {
    const entry = entries.find(value => value.startsWith(`${name}=`))
    if (entry) { try { return decodeURIComponent(entry.slice(name.length + 1)) || null } catch { return null } }
  }
  return null
}
export function canChangeOwner(actorRole: string, currentRole: string, nextRole?: string): boolean { return actorRole.toLowerCase() === 'owner' || (currentRole.toLowerCase() !== 'owner' && nextRole?.toLowerCase() !== 'owner') }
