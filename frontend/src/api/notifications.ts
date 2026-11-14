import { api, expectArray, expectRecord } from './client'
import type { Notification } from '../types/api'

const validNotification = (row: unknown) => !!row && typeof row === 'object' && typeof (row as Notification).id === 'number' && typeof (row as Notification).post_id === 'number' && typeof (row as Notification).recipient_agent_id === 'number' && typeof (row as Notification).status === 'string' && !!(row as Notification).reason_json && typeof (row as Notification).reason_json.explanation === 'string'
export const getNotifications = async (limit = 50, offset = 0) => expectArray<Notification>((await api.get('/notifications', { params: { limit, offset } })).data, validNotification, 'notifications')
export const markNotificationRead = async (id: number) => expectRecord<Notification>((await api.patch(`/notifications/${id}/read`)).data, row => typeof row.id === 'number' && typeof row.status === 'string', 'notification update')
