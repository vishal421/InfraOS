export interface License {
  feature: string
  description: string | null
  expires: string | null
  expired: boolean
}

export interface Device {
  id: string
  vendor: string
  hostname: string | null
  mgmt_host: string
  mgmt_port: number
  username: string | null
  verify_tls: boolean
  model: string | null
  serial: string | null
  os_version: string | null
  ha_state: string | null
  ha_peer_serial: string | null
  uptime_seconds: number | null
  licenses: License[]
  connection_status: string
  last_connectivity_check_at: string | null
  last_discovered_at: string | null
  last_config_collected_at: string | null
  created_at: string
  updated_at: string
}

export interface ConnectivityTestResult {
  status: string
  reachable: boolean
  tls_valid: boolean
  authenticated: boolean
  latency_ms: number | null
  error_detail: string | null
}

export interface DiffCategory {
  added: string[]
  removed: string[]
  changed: string[]
}

export interface ConfigVersionSummary {
  id: string
  version_num: number
  snapshot_type: string
  config_hash: string
  interface_count: number
  zone_count: number
  object_count: number
  policy_count: number
  diff_summary: Record<string, DiffCategory>
  is_drift: boolean
  collected_at: string
}

export interface NormalizedObject {
  name: string
  object_type: string
  definition: Record<string, unknown>
  in_use: boolean | null
}

export interface NormalizedPolicy {
  name: string
  policy_type: string
  rule_order: number
  source_zones: string[]
  destination_zones: string[]
  source: string[]
  destination: string[]
  application: string[]
  service: string[]
  action: string | null
  hit_count: number | null
}

export interface NormalizedInterface {
  name: string
  zone: string | null
  virtual_router: string | null
  ip_addresses: string[]
  mode: string | null
  enabled: boolean
}

export interface NormalizedZone {
  name: string
  interfaces: string[]
}

export interface ConfigVersionDetail extends ConfigVersionSummary {
  interfaces: NormalizedInterface[]
  zones: NormalizedZone[]
  objects: NormalizedObject[]
  policies: NormalizedPolicy[]
}

export interface MetricPoint {
  metric_name: string
  value: number
  unit: string | null
  dimensions: Record<string, string>
  recorded_at: string
}

export interface InterfaceStatus {
  name: string
  zone: string | null
  admin_up: boolean
  oper_up: boolean
  ip_addresses: string[]
  speed_mbps: number | null
  duplex: string | null
  mtu: number | null
  in_bytes: number | null
  out_bytes: number | null
  in_packets: number | null
  out_packets: number | null
  in_errors: number | null
  out_errors: number | null
  in_drops: number | null
  out_drops: number | null
  in_bps: number | null
  out_bps: number | null
  collected_at: string
}

export interface HealthEvent {
  id: string
  severity: 'info' | 'warning' | 'critical'
  category: string
  message: string
  occurred_at: string
  resolved_at: string | null
}

export interface DigitalTwin {
  device: Device
  latest_config: ConfigVersionSummary | null
  latest_metrics: Record<string, MetricPoint>
  active_health_events: HealthEvent[]
  generated_at: string
  cache_hit: boolean
}

export interface ChangeRequest {
  id: string
  device_id: string
  action: string
  target_type: string
  target_name: string
  element_xml: string | null
  payload: Record<string, unknown>
  status: string
  validation_errors: string[]
  validation_warnings: string[]
  impact_summary: { affected_policies?: string[]; affected_count?: number; note?: string }
  requested_by: string | null
  approved_by: string | null
  rejection_reason: string | null
  commit_job_id: string | null
  error_detail: string | null
  created_at: string
  updated_at: string
}

export interface TopologyNode {
  id: string
  type: string
  label: string
}

export interface TopologyEdge {
  source: string
  target: string
  relationship_type: string
}

export interface TopologyGraph {
  device_id: string
  version_num: number
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export interface LogEntryRecord {
  id: string
  log_type: string
  raw: Record<string, string>
  logged_at: string
  collected_at: string
}

export interface BestPracticeFinding {
  category: string
  severity: 'low' | 'medium' | 'high'
  target: string
  message: string
}

export interface BestPracticeReport {
  device_id: string
  config_version: number
  security_score: number
  finding_count: number
  findings_by_category: Record<string, number>
  findings: BestPracticeFinding[]
}
