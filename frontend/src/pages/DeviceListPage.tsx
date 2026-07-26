import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type CreateDevicePayload } from '../api/client'
import type { Device } from '../types'
import { StatusBadge } from '../components/StatusPulse'
import { AddDeviceModal } from '../components/AddDeviceModal'

export function DeviceListPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      const data = await api.listDevices()
      setDevices(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load devices')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleCreate(payload: CreateDevicePayload) {
    await api.createDevice(payload)
    await refresh()
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold">Firewalls</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-1">
            {devices.length} device{devices.length !== 1 ? 's' : ''} under management
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 text-sm rounded-lg bg-[var(--color-signal)] text-white hover:bg-[var(--color-signal-dim)]"
        >
          + Add Firewall
        </button>
      </div>

      {error && <p className="text-sm text-[var(--color-status-critical)] mb-4">{error}</p>}

      {loading ? (
        <div className="text-sm text-[var(--color-text-muted)]">Loading…</div>
      ) : devices.length === 0 ? (
        <div className="border border-dashed border-[var(--color-hairline)] rounded-xl p-12 text-center">
          <p className="text-[var(--color-text-secondary)]">No firewalls added yet.</p>
          <button
            onClick={() => setShowAddModal(true)}
            className="mt-3 text-sm text-[var(--color-signal)] hover:underline"
          >
            Add your first Palo Alto firewall
          </button>
        </div>
      ) : (
        <div className="border border-[var(--color-hairline)] rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[var(--color-surface)] text-left text-xs text-[var(--color-text-muted)] uppercase tracking-wide">
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Hostname</th>
                <th className="px-4 py-3 font-medium">Management IP</th>
                <th className="px-4 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium">PAN-OS</th>
                <th className="px-4 py-3 font-medium">HA</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-hairline)]">
              {devices.map((d) => (
                <tr key={d.id} className="hover:bg-[var(--color-surface)] transition-colors">
                  <td className="px-4 py-3">
                    <StatusBadge status={d.connection_status} />
                  </td>
                  <td className="px-4 py-3">
                    <Link to={`/devices/${d.id}`} className="text-[var(--color-signal)] hover:underline">
                      {d.hostname || '(not yet discovered)'}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--color-text-secondary)]">
                    {d.mgmt_host}:{d.mgmt_port}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-text-secondary)]">{d.model || '—'}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--color-text-secondary)]">
                    {d.os_version || '—'}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-text-secondary)]">{d.ha_state || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAddModal && <AddDeviceModal onClose={() => setShowAddModal(false)} onCreate={handleCreate} />}
    </div>
  )
}
