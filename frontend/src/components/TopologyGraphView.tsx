import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api/client'
import type { TopologyGraph } from '../types'

const TYPE_COLOR: Record<string, string> = {
  device: '#5b8cff',
  interface: '#8d96a8',
  zone: '#3ecf8e',
  policy: '#f5a623',
  object: '#5b6473',
  application: '#ff5d5d',
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string
  type: string
  label: string
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  relationship_type: string
}

export function TopologyGraphView({ deviceId }: { deviceId: string }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [graph, setGraph] = useState<TopologyGraph | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getTopology(deviceId)
      .then(setGraph)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load topology'))
  }, [deviceId])

  useEffect(() => {
    if (!graph || !svgRef.current) return

    const width = 900
    const height = 560

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }))
    const nodeById = new Map(nodes.map((n) => [n.id, n]))
    const links: SimLink[] = graph.edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, relationship_type: e.relationship_type }))

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(90)
      )
      .force('charge', d3.forceManyBody().strength(-220))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(28))

    const g = svg.append('g')

    svg.call(
      d3.zoom<SVGSVGElement, unknown>().on('zoom', (event) => {
        g.attr('transform', event.transform)
      }) as never
    )

    const link = g
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', 'var(--color-hairline)')
      .attr('stroke-width', 1.5)

    const node = g
      .append('g')
      .selectAll<SVGCircleElement, SimNode>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d) => (d.type === 'device' ? 14 : d.type === 'policy' ? 10 : 8))
      .attr('fill', (d) => TYPE_COLOR[d.type] ?? '#6b7280')
      .attr('stroke', '#0a0d12')
      .attr('stroke-width', 2)
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = null
            d.fy = null
          }) as never
      )

    const label = g
      .append('g')
      .selectAll('text')
      .data(nodes)
      .join('text')
      .text((d) => d.label)
      .attr('font-size', 10)
      .attr('font-family', 'IBM Plex Mono, monospace')
      .attr('fill', 'var(--color-text-secondary)')
      .attr('dx', 12)
      .attr('dy', 4)

    node.append('title').text((d) => `${d.type}: ${d.label}`)

    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0)

      node.attr('cx', (d) => d.x ?? 0).attr('cy', (d) => d.y ?? 0)
      label.attr('x', (d) => d.x ?? 0).attr('y', (d) => d.y ?? 0)
    })

    return () => {
      simulation.stop()
    }
  }, [graph])

  if (error) {
    return <p className="text-sm text-[var(--color-text-muted)] p-6 text-center">{error}</p>
  }
  if (!graph) {
    return <p className="text-sm text-[var(--color-text-muted)] p-6 text-center">Loading topology…</p>
  }

  return (
    <div>
      <div className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-hairline)] text-xs">
        {Object.entries(TYPE_COLOR).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
        <span className="text-[var(--color-text-muted)] ml-auto">
          v{graph.version_num} · {graph.nodes.length} nodes · {graph.edges.length} edges · scroll to zoom, drag to pan/reposition
        </span>
      </div>
      <svg ref={svgRef} viewBox="0 0 900 560" className="w-full h-[560px]" />
    </div>
  )
}
