import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, ErrorState, formatDate } from '../components/common/UI'
import { get, post } from './api'
import { ActionNotice, Resource, useAction, useResource } from './common'
import { logout } from './Session'
import type { InvitationPreview, Session } from './types'
export function JoinInvitation({ session, onSession }: { session: Session | null; onSession: (value: Session) => void }) {
  const [search] = useSearchParams()
  const token = search.get('token') || ''
  const navigate = useNavigate()
  const [existing, setExisting] = useState(false)
  const resource = useResource(() => get<InvitationPreview>(`/company-invitations/preview?token=${encodeURIComponent(token)}`), [token])
  const action = useAction()
  const login = useAction()
  const accept = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget))
    await action.run(async () => { onSession(await post<Session>('/company-invitations/accept', { token, ...(!session ? values : {}) })); navigate('/', { replace: true }) }, 'Invitation accepted.')
  }
  return <main className="auth-shell"><Card className="auth-card"><p className="eyebrow">Company invitation</p><h1>Join a workspace</h1>{!token ? <ErrorState message="This invitation link is incomplete." /> : <Resource resource={resource}>{invitation => <div className="form-stack"><p className="body-copy"><strong>{invitation.company_name}</strong> invited <strong>{invitation.email}</strong> as {invitation.role}. Expires {formatDate(invitation.expires_at)}.</p>{session && session.user.email.toLowerCase() !== invitation.email.toLowerCase() ? <><p role="alert" className="form-error">You are signed in as {session.user.email}. Sign in with the invited address before accepting.</p><Button disabled={action.busy} onClick={() => void action.run(() => logout(`/join?token=${encodeURIComponent(token)}`))}>Sign out to use the invited account</Button></> : existing && !session ? <form className="form-stack" onSubmit={event => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); void login.run(async () => onSession(await post<Session>('/auth/login', values)), 'Signed in. Review and accept the invitation.') }}><label>Invited email<input name="email" type="email" required defaultValue={invitation.email} autoComplete="email" /></label><label>Password<input name="password" type="password" required autoComplete="current-password" /></label><ActionNotice action={login} /><Button type="submit" className="button-primary" disabled={login.busy}>Sign in to accept</Button><Button type="button" onClick={() => setExisting(false)}>Create an invited account instead</Button></form> : <form className="form-stack" onSubmit={event => void accept(event)}>{!session && <><label>Your name<input name="name" required maxLength={160} autoComplete="name" /></label><label>Create password<input name="password" type="password" required minLength={12} maxLength={1024} autoComplete="new-password" /><small className="muted">At least 12 characters. An account is created with the invited email.</small></label></>}<Button className="button-primary" type="submit" disabled={action.busy}>{action.busy ? 'Accepting…' : 'Accept company invitation'}</Button>{!session && <Button type="button" onClick={() => setExisting(true)}>I already have an account</Button>}</form>}<ActionNotice action={action} /></div>}</Resource>}<Link className="text-link section-gap" to="/">Back to AgentConnect →</Link></Card></main>
}
