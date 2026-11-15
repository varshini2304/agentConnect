import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import axios from 'axios'
import { apiErrorMessage } from '../api/client'
import { Button, EmptyState, ErrorState, Loading } from '../components/common/UI'
import { useRefreshKey } from '../hooks/useApiData'
import { limitFields } from './domain'
import type { Limits } from './types'

export function useResource<T>(loader: () => Promise<T>, dependencies: unknown[] = [], poll = false) {
  const refreshKey = useRefreshKey()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const generation = useRef(0)
  const reload = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    try { const result = await loader(); if (current === generation.current) { setData(result); setError('') } } catch (reason) { if (current === generation.current) { if (axios.isAxiosError(reason) && [401, 403, 404].includes(reason.response?.status || 0)) setData(null); setError(apiErrorMessage(reason)) } } finally { if (current === generation.current) setLoading(false) }
  }, dependencies)
  useEffect(() => {
    setData(null); void reload()
    const interval = poll ? window.setInterval(() => { if (!document.hidden) void reload() }, 10000) : undefined
    return () => { ++generation.current; window.clearInterval(interval) }
  }, [reload, refreshKey, poll])
  return { data, error, loading, reload, setData }
}
export function Resource<T>({ resource, children }: { resource: ReturnType<typeof useResource<T>>; children: (data: T) => ReactNode }) {
  if (!resource.data) return resource.error ? <ErrorState message={resource.error} retry={() => void resource.reload()} /> : <Loading />
  return <>{resource.error && <div role="alert" className="banner banner-warning">{resource.error}</div>}{children(resource.data)}</>
}
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const run = async (action: () => Promise<unknown>, message = 'Saved.') => {
    setBusy(true); setError(''); setSuccess('')
    try { await action(); setSuccess(message); return true } catch (reason) { setError(apiErrorMessage(reason)); return false } finally { setBusy(false) }
  }
  return { busy, error, success, run, clear: () => { setError(''); setSuccess('') } }
}
export function ActionNotice({ action }: { action: ReturnType<typeof useAction> }) { return <>{action.error && <p role="alert" className="form-error">{action.error}</p>}{action.success && <p role="status" className="success-notice">{action.success}</p>}</> }
export function Check({ label, checked, onChange, detail }: { label: string; checked: boolean; onChange: (value: boolean) => void; detail?: string }) { return <label className="checkbox-label"><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} /><span>{label}{detail && <small className="field-help">{detail}</small>}</span></label> }
export function LimitsEditor({ value, onChange, ceiling }: { value: Limits; onChange: (limits: Limits) => void; ceiling?: Partial<Limits> }) {
  return <div className="form-grid">{limitFields.map(field => <label key={field.key}>{field.label}<input required type="number" min={field.key === 'cooldown_seconds' ? Math.max(field.min, ceiling?.cooldown_seconds ?? field.min) : field.min} max={field.key === 'cooldown_seconds' ? field.max : Math.min(field.max, ceiling?.[field.key] ?? field.max)} step={field.step || 1} value={value[field.key]} onChange={event => onChange({ ...value, [field.key]: event.target.valueAsNumber })} /></label>)}</div>
}
export function NoRows({ title = 'Nothing here yet', detail = 'Create your first item to get started.' }: { title?: string; detail?: string }) { return <EmptyState title={title} detail={detail} /> }
export function RefreshButton({ reload, loading }: { reload: () => Promise<void>; loading: boolean }) { return <Button disabled={loading} onClick={() => void reload()}>{loading ? 'Refreshing…' : 'Refresh'}</Button> }
