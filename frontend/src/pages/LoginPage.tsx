import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login as apiLogin } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const result = await apiLogin(username, password)
      login(result.access_token, result.username, result.role)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-canvas)]">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm bg-[var(--color-surface)] border border-[var(--color-hairline)] rounded-xl p-8"
      >
        <h1 className="font-display text-xl font-semibold mb-1">InfraOS</h1>
        <p className="text-sm text-[var(--color-text-secondary)] mb-6">Palo Alto module — sign in</p>

        <label className="block mb-4">
          <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required className="input" />
        </label>
        <label className="block mb-6">
          <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="input"
          />
        </label>

        {error && <p className="text-sm text-[var(--color-status-critical)] mb-4">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2 rounded-lg bg-[var(--color-signal)] text-white hover:bg-[var(--color-signal-dim)] disabled:opacity-50"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
