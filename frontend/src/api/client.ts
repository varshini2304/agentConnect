import axios from 'axios'
import { companyScopeFor, csrfCookie } from '../workspace/access'

export class ApiResponseError extends Error {
  constructor(resource: string) { super(`The server returned an unexpected ${resource} response. Refresh the page and try again.`) }
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

let csrfRequest: Promise<string> | null = null
let activeCompanyId: number | null = null
export function setCompanyScope(companyId: number | null) { activeCompanyId = companyId }
export async function ensureCsrf(): Promise<string> {
  const cookie = csrfCookie(document.cookie)
  if (cookie) return cookie
  if (!csrfRequest) csrfRequest = api.get<{ csrf_token: string }>('/auth/csrf').then(response => {
    const token = csrfCookie(document.cookie) || response.data.csrf_token
    if (!token) throw new Error('Security verification is unavailable. Reload and try again.')
    return token
  }).finally(() => { csrfRequest = null })
  return csrfRequest
}
api.interceptors.request.use(async config => {
  const companyId = companyScopeFor(config.url || '', activeCompanyId)
  if (companyId !== null) config.headers['X-Company-ID'] = String(companyId)
  if (!['get', 'head', 'options'].includes((config.method || 'get').toLowerCase())) config.headers['X-CSRF-Token'] = await ensureCsrf()
  return config
})
api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/')) window.dispatchEvent(new Event('agentconnect:session-expired'))
  return Promise.reject(error)
})

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiResponseError) return error.message
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 429) {
      const seconds = Number(error.response.headers['retry-after'])
      return Number.isFinite(seconds) && seconds > 0 ? `Too many attempts. Try again in ${Math.ceil(seconds)} seconds.` : 'Too many attempts. Please wait before trying again.'
    }
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(item => `${item.loc?.slice(1).join(' · ') || 'Input'}: ${item.msg || 'Invalid value'}`).join('; ')
    if (error.code === 'ECONNABORTED') return 'The server took too long to respond. Please try again.'
    if (!error.response) return 'AgentConnect API is unavailable. Check that the backend is running.'
    return `Request failed (${error.response.status}). Please try again.`
  }
  if (error instanceof Error && error.message) return error.message
  return 'Something went wrong. Please try again.'
}

export function expectRecord<T>(value: unknown, valid: (row: Record<string, unknown>) => boolean, resource: string): T {
  if (!value || typeof value !== 'object' || Array.isArray(value) || !valid(value as Record<string, unknown>)) throw new ApiResponseError(resource)
  return value as T
}

export function expectArray<T>(value: unknown, valid: (row: unknown) => boolean, resource: string): T[] {
  if (!Array.isArray(value) || !value.every(valid)) throw new ApiResponseError(resource)
  return value as T[]
}
