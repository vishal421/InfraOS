import type { HealthEvent } from '../types'
import { SeverityBadge } from './SeverityBadge'

export function HealthEventsList({ events }: { events: HealthEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-sm text-[var(--color-text-muted)] py-6 text-center">
        No active health events. Everything's quiet.
      </div>
    )
  }

  return (
    <ul className="divide-y divide-[var(--color-hairline)]">
      {events.map((event) => (
        <li key={event.id} className="px-4 py-3 flex items-start gap-3">
          <SeverityBadge severity={event.severity} />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-[var(--color-text-primary)]">{event.message}</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              {event.category} · {new Date(event.occurred_at).toLocaleString()}
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}
