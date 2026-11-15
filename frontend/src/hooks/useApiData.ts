import axios from 'axios'
import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'

export function useRefreshKey() {
  const [key, setKey] = useState(0)
  useEffect(() => {
    const refresh = () => setKey(value => value + 1)
    window.addEventListener('agentconnect:refresh', refresh)
    return () => window.removeEventListener('agentconnect:refresh', refresh)
  }, [])
  return key
}

export function useApiData<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try { setData(await loader()) } catch (reason) { if (axios.isAxiosError(reason) && [401, 403, 404].includes(reason.response?.status || 0)) setData(null); setError(apiErrorMessage(reason)) }
    finally { setLoading(false) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { void reload() }, [reload])
  return { data, loading, error, reload, setData }
}
