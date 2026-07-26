import { useState } from 'react'
import type { CreateDevicePayload } from '../api/client'

export function AddDeviceModal({
  onClose,
  onCreate,
}: {
  onClose: () => void
  onCreate: (payload: CreateDevicePayload) => Promise<void>
}) {
  const [form, setForm] = useState<CreateDevicePayload>({
    mgmt_host: '',
    mgmt_port: 443,
    username: '',
    password: '',
    verify_tls: true,
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await onCreate(form)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add firewall')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--color-surface)] border border-[var(--color-hairline)] rounded-xl w-full max-w-md p-6">
        <h2 className="font-display text-lg font-semibold mb-4">Add Palo Alto Firewall</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Management host / IP">
            <input
              required
              value={form.mgmt_host}
              onChange={(e) => setForm({ ...form, mgmt_host: e.target.value })}
              placeholder="192.168.1.1"
              className="input"
            />
          </Field>
          <Field label="Port">
            <input
              type="number"
              required
              value={form.mgmt_port}
              onChange={(e) => setForm({ ...form, mgmt_port: Number(e.target.value) })}
              className="input"
            />
          </Field>
          <Field label="Username">
            <input
              required
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              placeholder="admin"
              className="input"
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="input"
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
            <input
              type="checkbox"
              checked={form.verify_tls}
              onChange={(e) => setForm({ ...form, verify_tls: e.target.checked })}
            />
            Verify TLS certificate
          </label>

          {error && <p className="text-sm text-[var(--color-status-critical)]">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-sm rounded-lg bg-[var(--color-signal)] text-white hover:bg-[var(--color-signal-dim)] disabled:opacity-50"
            >
              {submitting ? 'Adding…' : 'Add Firewall'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs text-[var(--color-text-secondary)] mb-1">{label}</span>
      {children}
    </label>
  )
}
