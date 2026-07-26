import type { ConfigVersionSummary } from '../types'

function totalsFor(version: ConfigVersionSummary) {
  let added = 0
  let removed = 0
  let changed = 0
  for (const category of Object.values(version.diff_summary)) {
    added += category.added.length
    removed += category.removed.length
    changed += category.changed.length
  }
  return { added, removed, changed }
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function ConfigVersionLog({
  versions,
  onSelect,
}: {
  versions: ConfigVersionSummary[]
  onSelect?: (version: ConfigVersionSummary) => void
}) {
  if (versions.length === 0) {
    return (
      <div className="text-sm text-[var(--color-text-muted)] py-6 text-center">
        No configuration collected yet. Run a collection to start the version history.
      </div>
    )
  }

  return (
    <ul className="divide-y divide-[var(--color-hairline)]">
      {versions.map((v) => {
        const { added, removed, changed } = totalsFor(v)
        const shortHash = v.config_hash.slice(0, 7)
        return (
          <li key={v.id}>
            <button
              onClick={() => onSelect?.(v)}
              className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-[var(--color-surface-raised)] transition-colors"
            >
              <span className="font-mono text-xs text-[var(--color-text-muted)] w-16 shrink-0">
                v{v.version_num}
              </span>
              <span className="font-mono text-xs text-[var(--color-signal)] w-20 shrink-0">
                {shortHash}
              </span>
              <span className="flex-1 min-w-0 truncate text-sm text-[var(--color-text-secondary)]">
                {v.interface_count} interfaces · {v.zone_count} zones · {v.object_count} objects ·{' '}
                {v.policy_count} policies
              </span>
              <span className="font-mono text-xs shrink-0 flex gap-2">
                {added > 0 && <span className="text-[var(--color-status-ok)]">+{added}</span>}
                {removed > 0 && <span className="text-[var(--color-status-critical)]">-{removed}</span>}
                {changed > 0 && <span className="text-[var(--color-status-warning)]">~{changed}</span>}
                {added === 0 && removed === 0 && changed === 0 && (
                  <span className="text-[var(--color-text-muted)]">baseline</span>
                )}
              </span>
              {v.is_drift && (
                <span className="text-xs px-2 py-0.5 rounded bg-[color-mix(in_srgb,var(--color-status-warning)_15%,transparent)] text-[var(--color-status-warning)] shrink-0">
                  drift
                </span>
              )}
              <span className="text-xs text-[var(--color-text-muted)] w-16 text-right shrink-0">
                {timeAgo(v.collected_at)}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
