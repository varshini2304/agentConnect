import type { ReactNode } from 'react'
import { ErrorState } from '../components/common/UI'
import { useSession } from './Session'
export function PermissionGate({ permission, children }: { permission: string | string[]; children: ReactNode }) {
  const { can } = useSession()
  const allowed = (Array.isArray(permission) ? permission : [permission]).some(can)
  return allowed ? <>{children}</> : <ErrorState message="Your role does not allow access to this page. Ask a company owner to review your permissions." />
}
