import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'

export function Button({ className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`} {...props}>{children}</button>
}

export function PageHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="page-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p className="muted heading-copy">{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>
}

export function Loading({ label = 'Loading AgentConnect data…' }: { label?: string }) {
  return <div className="state-card"><LoaderCircle className="spin" size={19} /><span>{label}</span></div>
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="state-card error-state"><AlertCircle size={19} /><span>{message}</span>{retry && <Button onClick={retry}>Try again</Button>}</div>
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><div className="empty-mark">A</div><h3>{title}</h3><p>{detail}</p></div>
}

export function Status({ value }: { value: string }) {
  return <span className={`status status-${value.toLowerCase()}`}>{value.replaceAll('_', ' ')}</span>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>
}

export function formatDate(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}
