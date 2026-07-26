import { Outlet, Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function AppLayout() {
  const { username, role, logout } = useAuth()
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 shrink-0 border-r border-[var(--color-hairline)] bg-[var(--color-surface)] flex flex-col">
        <div className="px-5 py-5 border-b border-[var(--color-hairline)]">
          <Link to="/" className="font-display text-lg font-semibold tracking-tight">
            InfraOS
          </Link>
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">Palo Alto module</p>
        </div>
        <nav className="flex-1 px-3 py-4">
          <Link
            to="/"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)]"
          >
            Firewalls
          </Link>
        </nav>
        <div className="px-5 py-4 border-t border-[var(--color-hairline)]">
          <p className="text-sm text-[var(--color-text-primary)]">{username}</p>
          <p className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide mb-2">{role}</p>
          <button onClick={logout} className="text-xs text-[var(--color-signal)] hover:underline">
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  )
}
