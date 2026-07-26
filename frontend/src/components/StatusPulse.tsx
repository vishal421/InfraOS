const STATUS_COLOR: Record<string, string> = {
  online: 'bg-[var(--color-status-ok)]',
  unreachable: 'bg-[var(--color-status-critical)]',
  auth_failed: 'bg-[var(--color-status-critical)]',
  tls_error: 'bg-[var(--color-status-critical)]',
  unsupported_version: 'bg-[var(--color-status-warning)]',
  unknown: 'bg-[var(--color-status-unknown)]',
}

export function StatusPulse({ status, size = 8 }: { status: string; size?: number }) {
  const color = STATUS_COLOR[status] ?? STATUS_COLOR.unknown
  const isOnline = status === 'online'
  return (
    <span
      className={`inline-block rounded-full ${color} ${isOnline ? 'pulse-online' : ''}`}
      style={{ width: size, height: size }}
      aria-label={`Status: ${status}`}
    />
  )
}

export function StatusBadge({ status }: { status: string }) {
  const labelMap: Record<string, string> = {
    online: 'Online',
    unreachable: 'Unreachable',
    auth_failed: 'Auth failed',
    tls_error: 'TLS error',
    unsupported_version: 'Unsupported version',
    unknown: 'Unknown',
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
      <StatusPulse status={status} />
      {labelMap[status] ?? status}
    </span>
  )
}
