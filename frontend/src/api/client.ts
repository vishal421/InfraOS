import type {
  ConfigVersionDetail,
  ConfigVersionSummary,
  ConnectivityTestResult,
  Device,
  DigitalTwin,
  HealthEvent,
  InterfaceStatus,
  MetricPoint,
} from '../types'
import type { BestPracticeReport, ChangeRequest, LogEntryRecord, TopologyGraph } from '../types'
import { getStoredToken } from '../auth/AuthContext'

const BASE = '/api/v1'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getStoredToken()
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...options,
  })
  if (res.status === 401) {
    localStorage.removeItem('infraos_auth')
    window.location.href = '/login'
    throw new Error('Session expired — please log in again')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || detail
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export interface CreateDevicePayload {
  mgmt_host: string
  mgmt_port: number
  username: string
  password: string
  verify_tls: boolean
}

export async function login(username: string, password: string) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Login failed')
  }
  return res.json() as Promise<{ access_token: string; role: string; username: string }>
}

export const api = {
  listDevices: () => request<Device[]>('/devices'),
  getDevice: (id: string) => request<Device>(`/devices/${id}`),
  createDevice: (payload: CreateDevicePayload) =>
    request<Device>('/devices', { method: 'POST', body: JSON.stringify(payload) }),
  deleteDevice: (id: string) => request<void>(`/devices/${id}`, { method: 'DELETE' }),

  testConnectivity: (id: string) =>
    request<ConnectivityTestResult>(`/devices/${id}/test-connectivity`, { method: 'POST' }),
  discoverDevice: (id: string) => request<Device>(`/devices/${id}/discover`, { method: 'POST' }),

  collectConfig: (id: string, snapshotType: 'running' | 'candidate' = 'running') =>
    request<ConfigVersionDetail>(`/devices/${id}/config/collect?snapshot_type=${snapshotType}`, {
      method: 'POST',
    }),
  listConfigVersions: (id: string, snapshotType = 'running') =>
    request<ConfigVersionSummary[]>(`/devices/${id}/config/versions?snapshot_type=${snapshotType}`),
  getConfigVersion: (id: string, versionId: string) =>
    request<ConfigVersionDetail>(`/devices/${id}/config/versions/${versionId}`),
  getLatestConfig: (id: string, snapshotType = 'running') =>
    request<ConfigVersionDetail>(`/devices/${id}/config/latest?snapshot_type=${snapshotType}`),

  collectMetrics: (id: string) =>
    request<MetricPoint[]>(`/devices/${id}/metrics/collect`, { method: 'POST' }),
  getMetricHistory: (id: string, metricName: string, sinceMinutes = 60, plane?: 'control' | 'data') => {
    const params = new URLSearchParams({
      metric_name: metricName,
      since_minutes: String(sinceMinutes),
    })
    if (plane) params.set('plane', plane)
    return request<MetricPoint[]>(`/devices/${id}/metrics/history?${params.toString()}`)
  },

  listHealthEvents: (id: string, activeOnly = true) =>
    request<HealthEvent[]>(`/devices/${id}/health-events?active_only=${activeOnly}`),

  getInterfaces: (id: string) => request<InterfaceStatus[]>(`/devices/${id}/interfaces`),

  getDigitalTwin: (id: string, useCache = true) =>
    request<DigitalTwin>(`/devices/${id}/twin?use_cache=${useCache}`),

  listChanges: (deviceId: string) => request<ChangeRequest[]>(`/devices/${deviceId}/changes`),
  createChange: (
    deviceId: string,
    payload: { action: string; target_type: string; target_name: string; element_xml?: string }
  ) => request<ChangeRequest>(`/devices/${deviceId}/changes`, { method: 'POST', body: JSON.stringify(payload) }),
  validateChange: (changeId: string) =>
    request<ChangeRequest>(`/changes/${changeId}/validate`, { method: 'POST' }),
  approveChange: (changeId: string) =>
    request<ChangeRequest>(`/changes/${changeId}/approve`, { method: 'POST', body: JSON.stringify({}) }),
  rejectChange: (changeId: string, reason: string) =>
    request<ChangeRequest>(`/changes/${changeId}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  pushChange: (changeId: string) => request<ChangeRequest>(`/changes/${changeId}/push`, { method: 'POST' }),
  commitChange: (changeId: string) => request<ChangeRequest>(`/changes/${changeId}/commit`, { method: 'POST' }),

  getTopology: (deviceId: string) => request<TopologyGraph>(`/devices/${deviceId}/topology`),

  collectLogs: (deviceId: string, logType: string, sinceMinutes = 60) =>
    request<{ collected: number }>(
      `/devices/${deviceId}/logs/collect?log_type=${logType}&since_minutes=${sinceMinutes}`,
      { method: 'POST' }
    ),
  searchLogs: (deviceId: string, logType?: string, q?: string, sinceMinutes = 1440) => {
    const params = new URLSearchParams({ since_minutes: String(sinceMinutes) })
    if (logType) params.set('log_type', logType)
    if (q) params.set('q', q)
    return request<LogEntryRecord[]>(`/devices/${deviceId}/logs/search?${params.toString()}`)
  },
  correlateLogs: (deviceId: string) =>
    request<{ total_traffic_logs: number; matched_by_policy: Record<string, number>; unmatched_count: number }>(
      `/devices/${deviceId}/logs/correlate`
    ),

  getBestPractice: (deviceId: string) => request<BestPracticeReport>(`/devices/${deviceId}/best-practice`),

  downloadReport: async (deviceId: string, reportType: string) => {
    const token = getStoredToken()
    const res = await fetch(`${BASE}/devices/${deviceId}/reports/${reportType}?format=pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`Failed to generate report (${res.status})`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `infraos-${reportType}-report.pdf`
    a.click()
    URL.revokeObjectURL(url)
  },
}
