import { api } from '../api/client'
export async function get<T>(path: string): Promise<T> { return (await api.get<T>(path)).data }
export async function post<T>(path: string, data: unknown): Promise<T> { return (await api.post<T>(path, data)).data }
export async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData()
  body.append('document', file)
  return (await api.post<T>(path, body, { timeout: 120000, headers: { 'Content-Type': 'multipart/form-data' } })).data
}
export async function put<T>(path: string, data: unknown): Promise<T> { return (await api.put<T>(path, data)).data }
export async function patch<T>(path: string, data: unknown): Promise<T> { return (await api.patch<T>(path, data)).data }
export async function remove(path: string): Promise<void> { await api.delete(path) }
