import axios from 'axios'

export class ApiResponseError extends Error {
  constructor(resource: string) { super(`The server returned an unexpected ${resource} response. Refresh the page and try again.`) }
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiResponseError) return error.message
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
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
