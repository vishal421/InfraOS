import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { StatusPulse } from './StatusPulse'
import type { InterfaceStatus } from '../types'

const POLL_INTERVAL_MS = 5000

function formatBps(bps: number | null): string {
  if (bps === null || Number.isNaN(bps)) return '—'
  if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(2)} Gbps`
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`
  if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`
  return `${bps.toFixed(0)} bps`
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(2)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(2)} MB`
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(1)} KB`
  return `${bytes} B`
}

export function InterfacesPanel({ deviceId }: { deviceId: string }) {
  const [interfaces, setInterfaces] = useState<InterfaceStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState(true)
  const [lastPolled, setLastPolled] = useState<Date | null>(null)
  const liveRef = useRef(live)
  liveRef.current = live

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const data = await api.getInterfaces(deviceId)
        if (cancelled) return
        setInterfaces(data)
        setLastPolled(new Date())
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load interfaces')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    poll()
    const interval = setInterval(() => {
      if (liveRef.current) poll()
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [deviceId])

  if (loading) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">Polling device for interface status…</p>
  }

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-hairline)] bg-[var(--color-surface)]">
        <p className="text-xs text-[var(--color-text-muted)]">
          {lastPolled ? `Last polled ${lastPolled.toLocaleTimeString()}` : 'Not polled yet'}
        </p>
        <button
          onClick={() => setLive((v) => !v)}
          className={`px-2.5 py-1 text-xs rounded-md border ${
            live
              ? 'border-[var(--color-status-ok)] text-[var(--color-status-ok)]'
              : 'border-[var(--color-hairline)] text-[var(--color-text-muted)]'
          }`}
        >
          {live ? '● Live (5s)' : 'Paused'}
        </button>
      </div>

      {error && <p className="px-4 py-2 text-sm text-[var(--color-status-critical)]">{error}</p>}

      {interfaces.length === 0 ? (
        <p className="p-4 text-sm text-[var(--color-text-muted)]">
          No interfaces reported by the device.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--color-text-muted)] uppercase tracking-wide">
              <th className="px-4 py-2 font-medium">Interface</th>
              <th className="px-4 py-2 font-medium">Link</th>
              <th className="px-4 py-2 font-medium">Zone</th>
              <th className="px-4 py-2 font-medium">IP address(es)</th>
              <th className="px-4 py-2 font-medium">Speed</th>
              <th className="px-4 py-2 font-medium">RX</th>
              <th className="px-4 py-2 font-medium">TX</th>
              <th className="px-4 py-2 font-medium">Errors / Drops</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-hairline)]">
            {interfaces.map((iface) => (
              <tr key={iface.name}>
                <td className="px-4 py-2 font-mono text-xs">{iface.name}</td>
                <td className="px-4 py-2">
                  <span className="inline-flex items-center gap-2">
                    <StatusPulse status={iface.oper_up ? 'online' : 'unreachable'} />
                    <span className="text-xs text-[var(--color-text-secondary)]">
                      {iface.oper_up ? 'up' : 'down'}
                    </span>
                  </span>
                </td>
                <td className="px-4 py-2 text-[var(--color-text-secondary)]">{iface.zone || '—'}</td>
                <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
                  {iface.ip_addresses.length > 0 ? iface.ip_addresses.join(', ') : '—'}
                </td>
                <td className="px-4 py-2 text-[var(--color-text-secondary)]">
                  {iface.speed_mbps ? `${iface.speed_mbps} Mbps${iface.duplex ? ` (${iface.duplex})` : ''}` : '—'}
                </td>
                <td className="px-4 py-2">
                  <div className="font-mono text-xs text-[var(--color-signal)]">{formatBps(iface.in_bps)}</div>
                  <div className="text-[10px] text-[var(--color-text-muted)]">{formatBytes(iface.in_bytes)} total</div>
                </td>
                <td className="px-4 py-2">
                  <div className="font-mono text-xs text-[var(--color-status-warning)]">{formatBps(iface.out_bps)}</div>
                  <div className="text-[10px] text-[var(--color-text-muted)]">{formatBytes(iface.out_bytes)} total</div>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-muted)]">
                  {(iface.in_errors ?? 0) + (iface.out_errors ?? 0)} err · {(iface.in_drops ?? 0) + (iface.out_drops ?? 0)} drop
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
