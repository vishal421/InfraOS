import { useState } from 'react'
import { api } from '../api/client'
import type { LogEntryRecord } from '../types'

const LOG_TYPES = ['traffic', 'threat', 'system', 'config', 'tunnel']

export function LogsPanel({ deviceId }: { deviceId: string }) {
  const [logType, setLogType] = useState('traffic')
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<LogEntryRecord[]>([])
  const [correlation, setCorrelation] = useState<{
    total_traffic_logs: number
    matched_by_policy: Record<string, number>
    unmatched_count: number
  } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleCollect() {
    setBusy('collect')
    setError(null)
    try {
      const result = await api.collectLogs(deviceId, logType, 1440)
      await handleSearch()
      setError(`Collected ${result.collected} new ${logType} log(s).`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Collection failed')
    } finally {
      setBusy(null)
    }
  }

  async function handleSearch() {
    setBusy('search')
    try {
      const results = await api.searchLogs(deviceId, logType, query || undefined, 1440)
      setEntries(results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setBusy(null)
    }
  }

  async function handleCorrelate() {
    setBusy('correlate')
    try {
      setCorrelation(await api.correlateLogs(deviceId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Correlation failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-hairline)]">
        <select value={logType} onChange={(e) => setLogType(e.target.value)} className="input w-32">
          {LOG_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="filter (e.g. an IP or app name)"
          className="input flex-1"
        />
        <button
          onClick={handleSearch}
          disabled={busy === 'search'}
          className="px-3 py-2 text-sm rounded-lg border border-[var(--color-hairline)] hover:bg-[var(--color-surface-raised)]"
        >
          Search
        </button>
        <button
          onClick={handleCollect}
          disabled={busy === 'collect'}
          className="px-3 py-2 text-sm rounded-lg bg-[var(--color-signal)] text-white hover:bg-[var(--color-signal-dim)]"
        >
          {busy === 'collect' ? 'Collecting…' : 'Collect Logs'}
        </button>
        {logType === 'traffic' && (
          <button
            onClick={handleCorrelate}
            disabled={busy === 'correlate'}
            className="px-3 py-2 text-sm rounded-lg border border-[var(--color-hairline)] hover:bg-[var(--color-surface-raised)]"
          >
            Correlate → Policy
          </button>
        )}
      </div>

      {error && <p className="px-4 py-2 text-sm text-[var(--color-text-secondary)]">{error}</p>}

      {correlation && (
        <div className="px-4 py-3 border-b border-[var(--color-hairline)] bg-[var(--color-surface-raised)] text-sm">
          <p className="text-[var(--color-text-secondary)] mb-1">
            {correlation.total_traffic_logs} traffic log(s) examined · {correlation.unmatched_count} did not match a
            known policy
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(correlation.matched_by_policy).map(([policy, count]) => (
              <span key={policy} className="font-mono text-xs px-2 py-1 rounded bg-[var(--color-canvas)]">
                {policy}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {entries.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)] p-6 text-center">
          No logs loaded. Click Collect Logs, then Search.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--color-text-muted)] uppercase tracking-wide">
                <th className="px-4 py-2 font-medium">Time</th>
                {Object.keys(entries[0].raw).map((key) => (
                  <th key={key} className="px-4 py-2 font-medium">
                    {key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-hairline)]">
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-muted)]">
                    {new Date(e.logged_at).toLocaleString()}
                  </td>
                  {Object.entries(e.raw).map(([key, value]) => (
                    <td key={key} className="px-4 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
                      {value}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
