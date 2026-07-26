import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BestPracticeReport } from '../types'

const SEVERITY_COLOR: Record<string, string> = {
  high: 'text-[var(--color-status-critical)]',
  medium: 'text-[var(--color-status-warning)]',
  low: 'text-[var(--color-text-muted)]',
}

export function BestPracticePanel({ deviceId }: { deviceId: string }) {
  const [report, setReport] = useState<BestPracticeReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<string | null>(null)

  useEffect(() => {
    api
      .getBestPractice(deviceId)
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
  }, [deviceId])

  async function handleDownload(reportType: string) {
    setDownloading(reportType)
    try {
      await api.downloadReport(deviceId, reportType)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setDownloading(null)
    }
  }

  const scoreColor =
    report && report.security_score >= 80
      ? 'text-[var(--color-status-ok)]'
      : report && report.security_score >= 50
        ? 'text-[var(--color-status-warning)]'
        : 'text-[var(--color-status-critical)]'

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-hairline)]">
        <div>
          {report ? (
            <span className={`font-display text-2xl font-semibold ${scoreColor}`}>{report.security_score}/100</span>
          ) : (
            <span className="text-sm text-[var(--color-text-muted)]">{error || 'Loading…'}</span>
          )}
        </div>
        <div className="flex gap-2">
          {['executive', 'technical', 'security'].map((type) => (
            <button
              key={type}
              onClick={() => handleDownload(type)}
              disabled={downloading === type}
              className="px-3 py-1.5 text-xs rounded-lg border border-[var(--color-hairline)] hover:bg-[var(--color-surface-raised)] capitalize disabled:opacity-50"
            >
              {downloading === type ? 'Generating…' : `${type} PDF`}
            </button>
          ))}
        </div>
      </div>

      {report && report.findings.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)] p-6 text-center">
          No findings — configuration looks clean against the checks currently implemented.
        </p>
      )}

      {report && report.findings.length > 0 && (
        <ul className="divide-y divide-[var(--color-hairline)]">
          {report.findings.map((f, i) => (
            <li key={i} className="px-4 py-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs uppercase tracking-wide font-medium ${SEVERITY_COLOR[f.severity]}`}>
                  {f.severity}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">{f.category.replace(/_/g, ' ')}</span>
              </div>
              <p className="text-sm text-[var(--color-text-primary)]">{f.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
