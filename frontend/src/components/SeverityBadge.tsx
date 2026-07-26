const SEVERITY_STYLE: Record<string, string> = {
  critical: 'text-[var(--color-status-critical)] bg-[color-mix(in_srgb,var(--color-status-critical)_15%,transparent)]',
  warning: 'text-[var(--color-status-warning)] bg-[color-mix(in_srgb,var(--color-status-warning)_15%,transparent)]',
  info: 'text-[var(--color-signal)] bg-[color-mix(in_srgb,var(--color-signal)_15%,transparent)]',
}

export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.info
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wide ${style}`}>
      {severity}
    </span>
  )
}
