import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ChangeRequest } from '../types'
import { useAuth } from '../auth/AuthContext'

const STATUS_COLOR: Record<string, string> = {
  draft: 'text-[var(--color-text-muted)]',
  validation_failed: 'text-[var(--color-status-critical)]',
  pending_approval: 'text-[var(--color-status-warning)]',
  approved: 'text-[var(--color-signal)]',
  rejected: 'text-[var(--color-status-critical)]',
  pushed: 'text-[var(--color-signal)]',
  push_failed: 'text-[var(--color-status-critical)]',
  committed: 'text-[var(--color-status-ok)]',
  commit_failed: 'text-[var(--color-status-critical)]',
  rolled_back: 'text-[var(--color-text-muted)]',
}

export function ChangesPanel({ deviceId }: { deviceId: string }) {
  const { role, username } = useAuth()
  const [changes, setChanges] = useState<ChangeRequest[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ action: 'create', target_type: 'address_object', target_name: '', element_xml: '' })
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const canApprove = role === 'admin'
  const canPropose = role === 'operator' || role === 'admin'

  async function refresh() {
    setChanges(await api.listChanges(deviceId))
  }

  useEffect(() => {
    refresh()
  }, [deviceId])

  async function runAction(id: string, name: string, fn: () => Promise<unknown>) {
    setBusy(`${id}:${name}`)
    setError(null)
    try {
      await fn()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : `${name} failed`)
    } finally {
      setBusy(null)
    }
  }

  async function handlePropose(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api.createChange(deviceId, form)
      setForm({ action: 'create', target_type: 'address_object', target_name: '', element_xml: '' })
      setShowForm(false)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to propose change')
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-hairline)]">
        <p className="text-xs text-[var(--color-text-muted)]">
          Every change requires validate → approve (by someone other than the requester) → push → commit.
          No step can be skipped.
        </p>
        {canPropose && (
          <button
            onClick={() => setShowForm(!showForm)}
            className="px-3 py-1.5 text-sm rounded-lg bg-[var(--color-signal)] text-white hover:bg-[var(--color-signal-dim)] shrink-0 ml-4"
          >
            Propose Change
          </button>
        )}
      </div>

      {error && <p className="px-4 py-2 text-sm text-[var(--color-status-critical)]">{error}</p>}

      {showForm && (
        <form onSubmit={handlePropose} className="px-4 py-4 border-b border-[var(--color-hairline)] space-y-3 bg-[var(--color-surface-raised)]">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Action</span>
              <select
                value={form.action}
                onChange={(e) => setForm({ ...form, action: e.target.value })}
                className="input"
              >
                <option value="create">create</option>
                <option value="update">update</option>
                <option value="delete">delete</option>
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Target type</span>
              <select
                value={form.target_type}
                onChange={(e) => setForm({ ...form, target_type: e.target.value })}
                className="input"
              >
                <option value="address_object">address_object</option>
                <option value="address_group">address_group</option>
                <option value="service_object">service_object</option>
                <option value="security_policy">security_policy</option>
                <option value="nat_policy">nat_policy</option>
              </select>
            </label>
          </div>
          <label className="block">
            <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Target name</span>
            <input
              required
              value={form.target_name}
              onChange={(e) => setForm({ ...form, target_name: e.target.value })}
              className="input"
              placeholder="new-server-1"
            />
          </label>
          <label className="block">
            <span className="block text-xs text-[var(--color-text-secondary)] mb-1">Element XML (PAN-OS fragment)</span>
            <textarea
              value={form.element_xml}
              onChange={(e) => setForm({ ...form, element_xml: e.target.value })}
              className="input font-mono text-xs"
              rows={3}
              placeholder="<ip-netmask>10.0.2.5/32</ip-netmask>"
            />
          </label>
          <button type="submit" className="px-4 py-2 text-sm rounded-lg bg-[var(--color-signal)] text-white">
            Submit as {username}
          </button>
        </form>
      )}

      {changes.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)] p-6 text-center">No change requests yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-hairline)]">
          {changes.map((c) => (
            <li key={c.id} className="px-4 py-3">
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono text-sm">
                  {c.action} {c.target_type} <span className="text-[var(--color-signal)]">{c.target_name}</span>
                </span>
                <span className={`text-xs uppercase tracking-wide ${STATUS_COLOR[c.status] ?? ''}`}>
                  {c.status.replace('_', ' ')}
                </span>
              </div>
              <p className="text-xs text-[var(--color-text-muted)] mb-2">
                requested by {c.requested_by ?? 'unknown'}
                {c.approved_by && ` · approved by ${c.approved_by}`}
                {c.impact_summary?.affected_count !== undefined &&
                  ` · affects ${c.impact_summary.affected_count} polic${c.impact_summary.affected_count === 1 ? 'y' : 'ies'}`}
              </p>
              {c.validation_errors.length > 0 && (
                <p className="text-xs text-[var(--color-status-critical)] mb-2">
                  {c.validation_errors.join('; ')}
                </p>
              )}
              {c.error_detail && <p className="text-xs text-[var(--color-status-critical)] mb-2">{c.error_detail}</p>}

              <div className="flex gap-2">
                {c.status === 'draft' && canPropose && (
                  <ActionBtn
                    busy={busy === `${c.id}:validate`}
                    onClick={() => runAction(c.id, 'validate', () => api.validateChange(c.id))}
                  >
                    Validate
                  </ActionBtn>
                )}
                {c.status === 'pending_approval' && canApprove && (
                  <>
                    <ActionBtn
                      busy={busy === `${c.id}:approve`}
                      onClick={() => runAction(c.id, 'approve', () => api.approveChange(c.id))}
                    >
                      Approve
                    </ActionBtn>
                    <ActionBtn
                      busy={busy === `${c.id}:reject`}
                      onClick={() => runAction(c.id, 'reject', () => api.rejectChange(c.id, 'Rejected via dashboard'))}
                    >
                      Reject
                    </ActionBtn>
                  </>
                )}
                {c.status === 'approved' && canApprove && (
                  <ActionBtn busy={busy === `${c.id}:push`} onClick={() => runAction(c.id, 'push', () => api.pushChange(c.id))}>
                    Push to Candidate
                  </ActionBtn>
                )}
                {c.status === 'pushed' && canApprove && (
                  <ActionBtn busy={busy === `${c.id}:commit`} onClick={() => runAction(c.id, 'commit', () => api.commitChange(c.id))}>
                    Commit
                  </ActionBtn>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ActionBtn({ children, onClick, busy }: { children: React.ReactNode; onClick: () => void; busy: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="px-3 py-1 text-xs rounded-lg border border-[var(--color-hairline)] hover:bg-[var(--color-surface-raised)] disabled:opacity-50"
    >
      {busy ? '…' : children}
    </button>
  )
}
