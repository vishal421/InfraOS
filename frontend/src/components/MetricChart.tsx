import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { MetricPoint } from '../types'

export function MetricChart({
  title,
  data,
  unit,
  color = 'var(--color-signal)',
}: {
  title: string
  data: MetricPoint[]
  unit?: string | null
  color?: string
}) {
  const chartData = data.map((p) => ({
    time: new Date(p.recorded_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    value: p.value,
  }))

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-hairline)] rounded-lg p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">{title}</h3>
        {chartData.length > 0 && (
          <span className="font-mono text-lg text-[var(--color-text-primary)]">
            {chartData[chartData.length - 1].value.toFixed(1)}
            <span className="text-xs text-[var(--color-text-muted)] ml-1">{unit}</span>
          </span>
        )}
      </div>
      {chartData.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-xs text-[var(--color-text-muted)]">
          No data yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={128}>
          <LineChart data={chartData}>
            <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} axisLine={false} tickLine={false} width={32} />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--color-surface-raised)',
                border: '1px solid var(--color-hairline)',
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: 'var(--color-text-secondary)' }}
            />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
