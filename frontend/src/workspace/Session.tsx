import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import axios from 'axios'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiErrorMessage, setCompanyScope } from '../api/client'
import { Button, Card, ErrorState, Loading } from '../components/common/UI'
import { get, post } from './api'
import { hasPermission, selectedCompany } from './access'
import { JoinInvitation } from './JoinInvitation'
import type { Company, Session } from './types'
const sessionChannel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('agentconnect.session')
export function notifySessionChange() { sessionChannel?.postMessage('changed') }
const SessionContext = createContext<{ session: Session; company: Company; can: (permission: string) => boolean; refreshSession: () => Promise<void> } | null>(null)
export function useSession() { const value = useContext(SessionContext); if (!value) throw new Error('A workspace session is required.'); return value }
export async function switchCompany(id: number) { await post('/auth/workspace', { company_id: id }); notifySessionChange(); window.location.replace('/') }
export async function logout(destination = '/') { await post('/auth/logout', {}); notifySessionChange(); window.location.replace(destination) }
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [switching, setSwitching] = useState(false)
  const generation = useRef(0)
  const location = useLocation()
  const company = session ? selectedCompany(session) : undefined
  setCompanyScope(company?.id ?? null)
  const refreshSession = async () => { const current = ++generation.current; const value = await get<Session>('/auth/me'); if (current === generation.current) setSession(value) }
  useEffect(() => {
    let alive = true
    // Remove obsolete bearer credentials from older builds; cookie sessions never write browser storage.
    try { localStorage.removeItem('agentconnect.token'); localStorage.removeItem('agentconnect.company') } catch { /* Cookie sessions also work when browser storage is disabled. */ }
    const load = async () => {
      const current = ++generation.current
      try { const value = await get<Session>('/auth/me'); if (alive && current === generation.current) { setSession(value); setUnavailable(false); setError('') } }
      catch (reason) { if (alive && current === generation.current) { const status = axios.isAxiosError(reason) ? reason.response?.status : undefined; if (status === 401 || status === 403) setSession(null); setUnavailable(status !== 401); setError(status === 401 ? '' : apiErrorMessage(reason)) } }
      finally { if (alive && current === generation.current) setLoading(false) }
    }
    void get('/auth/csrf').then(load).catch(reason => { if (alive) { setError(apiErrorMessage(reason)); setUnavailable(true); setLoading(false) } })
    const expired = () => { void load() }
    const changed = () => window.location.replace('/')
    const restored = (event: PageTransitionEvent) => { if (event.persisted) window.location.reload() }
    const focused = () => { if (!document.hidden) void load() }
    const interval = window.setInterval(focused, 30000)
    window.addEventListener('agentconnect:session-expired', expired); window.addEventListener('pageshow', restored); window.addEventListener('focus', focused); sessionChannel?.addEventListener('message', changed)
    return () => { alive = false; window.clearInterval(interval); window.removeEventListener('agentconnect:session-expired', expired); window.removeEventListener('pageshow', restored); window.removeEventListener('focus', focused); sessionChannel?.removeEventListener('message', changed) }
  }, [])
  if (loading) return <div className="auth-shell"><Loading label="Opening your workspace…" /></div>
  const onSession = (value: Session) => { ++generation.current; setCompanyScope(selectedCompany(value)?.id ?? null); setError(''); setSession(value); notifySessionChange() }
  if (location.pathname === '/join') return <JoinInvitation session={session} onSession={onSession} />
  if (unavailable && !session) return <div className="auth-shell"><ErrorState message={error || 'Unable to open your workspace.'} retry={() => window.location.reload()} /></div>
  if (!session) return <AuthForm initialError={error} onSession={onSession} />
  if (!company) return <div className="auth-shell"><Card className="auth-card"><h1>{session.companies.length ? 'Choose an active workspace' : 'Workspace access ended'}</h1><p className="body-copy">{session.companies.length ? 'Your previous selection is unavailable. Select another company where you still have an active membership.' : 'Your account has no active company membership. Contact a company owner for access.'}</p><div className="form-stack">{session.companies.map(item => <Button key={item.id} disabled={switching} onClick={() => { setSwitching(true); void switchCompany(item.id).catch(reason => { setError(apiErrorMessage(reason)); setSwitching(false) }) }}>{item.name}</Button>)}<Button disabled={switching} onClick={() => void logout().catch(reason => setError(apiErrorMessage(reason)))}>Sign out</Button>{error && <p role="alert" className="form-error">{error}</p>}</div></Card></div>
  return <SessionContext.Provider key={`${session.user.id}:${company.id}:${[...company.permissions].sort().join(',')}`} value={{ session, company, can: permission => hasPermission(company, permission), refreshSession }}>{error && <p role="alert" className="form-error">Session refresh failed: {error}</p>}{children}</SessionContext.Provider>
}
function AuthForm({ initialError, onSession }: { initialError: string; onSession: (session: Session) => void }) {
  const navigate = useNavigate()
  const [register, setRegister] = useState(false)
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const values = Object.fromEntries(new FormData(event.currentTarget))
    if (!values.company_slug) delete values.company_slug
    try { onSession(await post<Session>(register ? '/auth/register' : '/auth/login', values)); navigate(register ? '/onboarding' : '/', { replace: true }) }
    catch (reason) { setError(!register && axios.isAxiosError(reason) && reason.response?.status === 401 ? 'Unable to sign in with those details.' : apiErrorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <main className="auth-shell"><Card className="auth-card"><p className="eyebrow">AgentConnect</p><h1>{register ? 'Create your workspace' : 'Welcome back'}</h1><p className="muted">Build company agents and collaborate across a trusted network.</p><form className="form-stack" onSubmit={event => void submit(event)}>
    {register && <><label>Your name<input name="name" autoComplete="name" required maxLength={160} /></label><label>Company name<input name="company_name" autoComplete="organization" required maxLength={160} /></label><label>Company handle (optional)<input name="company_slug" maxLength={90} pattern="[a-z0-9]+(-[a-z0-9]+)*" /><small className="muted">Lowercase letters, numbers and single hyphens. Generated if left blank.</small></label></>}
    <label>Work email<input type="email" name="email" autoComplete="email" required /></label><label>Password<input type="password" name="password" minLength={register ? 12 : undefined} maxLength={1024} autoComplete={register ? 'new-password' : 'current-password'} required />{register && <small className="muted">At least 12 characters.</small>}</label>
    {error && <p className="form-error" role="alert">{error}</p>}<Button className="button-primary" type="submit" disabled={busy}>{busy ? 'Please wait…' : register ? 'Create workspace' : 'Sign in'}</Button><Button type="button" onClick={() => { setRegister(!register); setError('') }}>{register ? 'Already have an account? Sign in' : 'Create an account'}</Button>
  </form></Card></main>
}
