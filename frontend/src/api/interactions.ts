import { api, expectArray, expectRecord } from './client'
import type { Interaction } from '../types/api'

const validInteraction = (row: Record<string, unknown>) => typeof row.id === 'number' && ['running', 'responded', 'skipped', 'failed'].includes(String(row.status))
export const getInteraction = async (id: number) => expectRecord<Interaction>((await api.get(`/interactions/${id}`)).data, validInteraction, 'interaction')
export const retryInteraction = async (id: number) => expectRecord<Interaction>((await api.post(`/interactions/${id}/retry`)).data, validInteraction, 'retried interaction')

export const getInteractions = async (limit = 50, offset = 0) => expectArray<Interaction>((await api.get('/interactions', { params: { limit, offset } })).data, row => !!row && typeof row === 'object' && validInteraction(row as Record<string, unknown>), 'interaction history')
