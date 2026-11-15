import { api, expectArray, expectRecord } from './client'
import type { Agent, AgentPatch } from '../types/api'

const validAgent = (row: unknown) => !!row && typeof row === 'object' && typeof (row as Agent).id === 'number' && typeof (row as Agent).company_name === 'string' && Array.isArray((row as Agent).interests) && (row as Agent).interests.every(item => typeof item.value === 'string' && typeof item.interest_type === 'string')
export const getAgents = async () => expectArray<Agent>((await api.get('/legacy/agents')).data, validAgent, 'agents list')
export const getAgent = async (id: number) => expectRecord<Agent>((await api.get(`/legacy/agents/${id}`)).data, row => typeof row.id === 'number' && typeof row.company_name === 'string' && Array.isArray(row.interests), 'agent profile')
export const updateAgent = async (id: number, patch: AgentPatch) => expectRecord<Agent>((await api.patch(`/legacy/agents/${id}`, patch)).data, row => typeof row.id === 'number' && typeof row.company_name === 'string' && Array.isArray(row.interests), 'updated agent profile')
