import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ConfigVersionDetail, ConfigVersionSummary, Device, HealthEvent, MetricPoint } from '../types'
import { StatusBadge } from '../components/StatusPulse'
import { MetricChart } from '../components/MetricChart'
import { ConfigVersionLog } from '../components/ConfigVersionLog'
import { HealthEventsList } from '../components/HealthEventsList'
import { ChangesPanel } from '../components/ChangesPanel'
import { TopologyGraphView } from '../components/TopologyGraphView'
import { LogsPanel } from '../components/LogsPanel'
import { BestPracticePanel } from '../components/BestPracticePanel'
import { InterfacesPanel } from '../components/InterfacesPanel'

type TabKey = 'overview' | 'configuration' | 'objects' | 'policies' | 'changes' | 'topology' | 'logs' | 'security' | 'interfaces'

function formatUptime(seconds: number | null): string {
  if (!seconds) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  return `${days}d ${hours}h`
}

export function DeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const navigate = useNavigate()
  const [device, setDevice] = useState<Device | null>(null)
  const [healthEvents, setHealthEvents] = useState<HealthEvent[]>([])
  const [versions, setVersions] = useState<ConfigVersionSummary[]>([])
  const [selectedVersion, setSelectedVersion] = useState<ConfigVersionDetail | null>(null)
  const [cpuHistory, setCpuHistory] = useState<MetricPoint[]>([])
  const [memHistory, setMemHistory] = useState<MetricPoint[]>([])
  const [dpCpuHistory, setDpCpuHistory] = useState<MetricPoint[]>([])
  const [dpMemHistory, setDpMemHistory] = useState<MetricPoint[]>([])
  const [sessionHistory, setSessionHistory] = useState<MetricPoint[]>([])
  const [tab, setTab] = useState<TabKey>('overview')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    if (!deviceId) return
    try {
      const d = await api.getDevice(deviceId)
      const isPaloAlto = d.vendor === 'paloalto'

      const [events, vers, cpu, mem, sess, dpCpu, dpMem] = await Promise.all([
        api.listHealthEvents(deviceId, false),
        api.listConfigVersions(deviceId),
        api.getMetricHistory(deviceId, 'cpu_utilization_pct', 120, isPaloAlto ? 'control' : undefined),
        api.getMetricHistory(deviceId, 'mem_utilization_pct', 120, isPaloAlto ? 'control' : undefined),
        api.getMetricHistory(deviceId, 'active_sessions', 120),
        isPaloAlto ? api.getMetricHistory(deviceId, 'cpu_utilization_pct', 120, 'data') : Promise.resolve([]),
        isPaloAlto ? api.getMetricHistory(deviceId, 'mem_utilization_pct', 120, 'data') : Promise.resolve([]),
      ])
      setDevice(d)
      setHealthEvents(events)
      setVersions(vers)
      setCpuHistory(cpu)
      setMemHistory(mem)
      setSessionHistory(sess)
      setDpCpuHistory(dpCpu)
      setDpMemHistory(dpMem)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load device')
    }
  }, [deviceId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  async function runAction(name: string, fn: () => Promise<unknown>) {
    if (!deviceId) return
    setBusy(name)
    setError(null)
    try {
      await fn()
      await loadAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : `${name} failed`)
    } finally {
      setBusy(null)
    }
  }

  async function handleDelete() {
    if (!deviceId) return
    if (!confirm('Remove this firewall from InfraOS? This does not change anything on the device itself.')) return
    await api.deleteDevice(deviceId)
    navigate('/')
  }

  if (!device) {
    return <div className="p-8 text-sm text-[var(--color-text-muted)]">{error || 'Loading…'}</div>
  }

  const expiredLicenses = device.licenses.filter((l) => l.expired)

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-display text-2xl font-semibold">{device.hostname || device.mgmt_host}</h1>
            <StatusBadge status={device.connection_status} />
          </div>
          <p className="font-mono text-xs text-[var(--color-text-muted)] mt-1">
            {device.mgmt_host}:{device.mgmt_port} · {device.serial || 'serial unknown'}
          </p>
        </div>
        <div className="flex gap-2">
          <ActionButton busy={busy === 'test'} onClick={() => runAction('test', () => api.testConnectivity(deviceId!))}>
            Test Connection
          </ActionButton>
          <ActionButton busy={busy === 'discover'} onClick={() => runAction('discover', () => api.discoverDevice(deviceId!))}>
            Discover
          </ActionButton>
          <ActionButton busy={busy === 'config'} onClick={() => runAction('config', () => api.collectConfig(deviceId!))}>
            Collect Config
          </ActionButton>
          <ActionButton busy={busy === 'metrics'} onClick={() => runAction('metrics', () => api.collectMetrics(deviceId!))}>
            Collect Metrics
          </ActionButton>
          <button
            onClick={handleDelete}
            className="px-3 py-2 text-sm rounded-lg text-[var(--color-status-critical)] hover:bg-[var(--color-surface-raised)]"
          >
            Remove
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-[var(--color-status-critical)] mt-3">{error}</p>}

      {/* Key facts row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-[var(--color-hairline)] rounded-xl overflow-hidden mt-6 mb-6">
        <Fact label="Model" value={device.model || '—'} />
        <Fact label="PAN-OS" value={device.os_version || '—'} mono />
        <Fact label="HA State" value={device.ha_state || '—'} />
        <Fact label="Uptime" value={formatUptime(device.uptime_seconds)} />
        <Fact
          label="Licenses"
          value={expiredLicenses.length > 0 ? `${expiredLicenses.length} expired` : 'all valid'}
          warn={expiredLicenses.length > 0}
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--color-hairline)] mb-6">
        {(['overview', 'interfaces', 'configuration', 'objects', 'policies', 'topology', 'logs', 'security', 'changes'] as TabKey[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm capitalize border-b-2 -mb-px transition-colors ${
              tab === t
                ? 'border-[var(--color-signal)] text-[var(--color-text-primary)]'
                : 'border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <MetricChart title="Control Plane CPU" data={cpuHistory} unit="%" color="var(--color-signal)" />
            <MetricChart title="Control Plane Memory" data={memHistory} unit="%" color="var(--color-status-warning)" />
            <MetricChart title="Active Sessions" data={sessionHistory} unit="" color="var(--color-status-ok)" />
          </div>
          {device.vendor === 'paloalto' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <MetricChart title="Data Plane CPU" data={dpCpuHistory} unit="%" color="var(--color-signal)" />
              <MetricChart title="Data Plane Packet Buffer" data={dpMemHistory} unit="%" color="var(--color-status-warning)" />
            </div>
          )}
          <Section title="Health Events">
            <HealthEventsList events={healthEvents} />
          </Section>
        </div>
      )}

      {tab === 'interfaces' && (
        <Section title="Interface Monitor — Live Traffic">
          <InterfacesPanel deviceId={deviceId!} />
        </Section>
      )}

      {tab === 'configuration' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Section title="Version History">
            <ConfigVersionLog
              versions={versions}
              onSelect={async (v) => setSelectedVersion(await api.getConfigVersion(deviceId!, v.id))}
            />
          </Section>
          <Section title={selectedVersion ? `v${selectedVersion.version_num} detail` : 'Select a version'}>
            {selectedVersion ? (
              <div className="p-4 space-y-3 text-sm">
                <DetailRow label="Config hash" value={selectedVersion.config_hash} mono />
                <DetailRow label="Interfaces" value={selectedVersion.interfaces.map((i) => i.name).join(', ') || '—'} />
                <DetailRow label="Zones" value={selectedVersion.zones.map((z) => z.name).join(', ') || '—'} />
                <DetailRow
                  label="Collected"
                  value={new Date(selectedVersion.collected_at).toLocaleString()}
                />
              </div>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] p-4">
                Click a version in the log to see its detail.
              </p>
            )}
          </Section>
        </div>
      )}

      {tab === 'objects' && (
        <Section title="Objects (latest configuration)">
          {selectedVersion || versions.length > 0 ? (
            <ObjectsTable deviceId={deviceId!} versionId={selectedVersion?.id ?? versions[0].id} />
          ) : (
            <p className="text-sm text-[var(--color-text-muted)] p-4">
              No configuration collected yet.
            </p>
          )}
        </Section>
      )}

      {tab === 'policies' && (
        <Section title="Security Policies (latest configuration)">
          {selectedVersion || versions.length > 0 ? (
            <PoliciesTable deviceId={deviceId!} versionId={selectedVersion?.id ?? versions[0].id} />
          ) : (
            <p className="text-sm text-[var(--color-text-muted)] p-4">
              No configuration collected yet.
            </p>
          )}
        </Section>
      )}

      {tab === 'topology' && (
        <Section title="Topology">
          <TopologyGraphView deviceId={deviceId!} />
        </Section>
      )}

      {tab === 'logs' && (
        <Section title="Log Analytics">
          <LogsPanel deviceId={deviceId!} />
        </Section>
      )}

      {tab === 'security' && (
        <Section title="Best Practice &amp; Reports">
          <BestPracticePanel deviceId={deviceId!} />
        </Section>
      )}

      {tab === 'changes' && (
        <Section title="Change Requests">
          <ChangesPanel deviceId={deviceId!} />
        </Section>
      )}
    </div>
  )
}

function ActionButton({
  children,
  onClick,
  busy,
}: {
  children: React.ReactNode
  onClick: () => void
  busy: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="px-3 py-2 text-sm rounded-lg border border-[var(--color-hairline)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)] disabled:opacity-50"
    >
      {busy ? '…' : children}
    </button>
  )
}

function Fact({ label, value, mono, warn }: { label: string; value: string; mono?: boolean; warn?: boolean }) {
  return (
    <div className="bg-[var(--color-surface)] px-4 py-3">
      <p className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide">{label}</p>
      <p
        className={`mt-1 text-sm ${mono ? 'font-mono' : ''} ${
          warn ? 'text-[var(--color-status-warning)]' : 'text-[var(--color-text-primary)]'
        }`}
      >
        {value}
      </p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-[var(--color-hairline)] rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--color-hairline)] bg-[var(--color-surface)]">
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      {children}
    </div>
  )
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2">
      <span className="text-[var(--color-text-muted)] w-28 shrink-0">{label}</span>
      <span className={`${mono ? 'font-mono text-xs' : ''} text-[var(--color-text-secondary)] break-all`}>
        {value}
      </span>
    </div>
  )
}

function ObjectsTable({ deviceId, versionId }: { deviceId: string; versionId: string }) {
  const [version, setVersion] = useState<ConfigVersionDetail | null>(null)
  useEffect(() => {
    api.getConfigVersion(deviceId, versionId).then(setVersion)
  }, [deviceId, versionId])

  if (!version) return <p className="p-4 text-sm text-[var(--color-text-muted)]">Loading…</p>
  if (version.objects.length === 0) return <p className="p-4 text-sm text-[var(--color-text-muted)]">No objects.</p>

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-[var(--color-text-muted)] uppercase tracking-wide">
          <th className="px-4 py-2 font-medium">Name</th>
          <th className="px-4 py-2 font-medium">Type</th>
          <th className="px-4 py-2 font-medium">Definition</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-[var(--color-hairline)]">
        {version.objects.map((o) => (
          <tr key={o.name}>
            <td className="px-4 py-2 font-mono text-xs">{o.name}</td>
            <td className="px-4 py-2 text-[var(--color-text-secondary)]">{o.object_type}</td>
            <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-muted)] truncate max-w-xs">
              {JSON.stringify(o.definition)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function PoliciesTable({ deviceId, versionId }: { deviceId: string; versionId: string }) {
  const [version, setVersion] = useState<ConfigVersionDetail | null>(null)
  useEffect(() => {
    api.getConfigVersion(deviceId, versionId).then(setVersion)
  }, [deviceId, versionId])

  if (!version) return <p className="p-4 text-sm text-[var(--color-text-muted)]">Loading…</p>
  if (version.policies.length === 0) return <p className="p-4 text-sm text-[var(--color-text-muted)]">No policies.</p>

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-[var(--color-text-muted)] uppercase tracking-wide">
          <th className="px-4 py-2 font-medium">#</th>
          <th className="px-4 py-2 font-medium">Name</th>
          <th className="px-4 py-2 font-medium">From → To</th>
          <th className="px-4 py-2 font-medium">Source</th>
          <th className="px-4 py-2 font-medium">Destination</th>
          <th className="px-4 py-2 font-medium">Action</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-[var(--color-hairline)]">
        {version.policies.map((p) => (
          <tr key={p.name}>
            <td className="px-4 py-2 text-[var(--color-text-muted)]">{p.rule_order}</td>
            <td className="px-4 py-2 font-mono text-xs">{p.name}</td>
            <td className="px-4 py-2 text-[var(--color-text-secondary)]">
              {p.source_zones.join(',')} → {p.destination_zones.join(',')}
            </td>
            <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
              {p.source.join(', ')}
            </td>
            <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
              {p.destination.join(', ')}
            </td>
            <td className="px-4 py-2">
              <span
                className={
                  p.action === 'allow' ? 'text-[var(--color-status-ok)]' : 'text-[var(--color-status-critical)]'
                }
              >
                {p.action}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
