// 轻量 SVG 图表：单 hue（--chart-1），无第三方图表库默认样式
export function LineChart({ points, series, height = 200, yMax, yLabel }: {
  points: string[]
  series: { name: string; color: string; values: (number | null)[] }[]
  height?: number; yMax?: number; yLabel?: string
}) {
  const W = 720, H = height, PL = 36, PR = 12, PT = 12, PB = 26
  const all = series.flatMap(s => s.values.filter((v): v is number => v != null))
  const max = yMax ?? Math.max(1, ...all)
  const x = (i: number) => PL + (i * (W - PL - PR)) / Math.max(1, points.length - 1)
  const y = (v: number) => PT + (1 - v / max) * (H - PT - PB)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img">
      {[0, 0.25, 0.5, 0.75, 1].map(t => (
        <g key={t}>
          <line x1={PL} x2={W - PR} y1={y(t * max)} y2={y(t * max)} stroke="#f0f1f2" />
          <text x={PL - 6} y={y(t * max) + 4} textAnchor="end" fontSize={10} fill="#5d5f60">
            {(t * max).toFixed(max <= 1.01 ? 2 : 0)}
          </text>
        </g>
      ))}
      {series.map((s, si) => {
        const d = s.values.map((v, i) => v == null ? null : `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).filter(Boolean).join(' ')
        return <g key={si}>
          <path d={d} fill="none" stroke={s.color} strokeWidth={2} />
          {s.values.map((v, i) => v == null ? null : <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={s.color} />)}
        </g>
      })}
      {points.map((p, i) => (
        <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize={10} fill="#5d5f60">{p}</text>
      ))}
      {yLabel && <text x={PL} y={8} fontSize={10} fill="#5d5f60">{yLabel}</text>}
    </svg>
  )
}

export function BarsChart({ labels, values, height = 180, color = '#1b6c80', suffix = '', yMax }: {
  labels: string[]; values: number[]; height?: number; color?: string; suffix?: string; yMax?: number
}) {
  const W = 720, H = height, PL = 36, PR = 12, PT = 16, PB = 40
  const max = yMax ?? Math.max(1, ...values)
  const bw = (W - PL - PR) / values.length
  const y = (v: number) => PT + (1 - v / max) * (H - PT - PB)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img">
      {[0, 0.5, 1].map(t => (
        <g key={t}>
          <line x1={PL} x2={W - PR} y1={y(t * max)} y2={y(t * max)} stroke="#f0f1f2" />
          <text x={PL - 6} y={y(t * max) + 4} textAnchor="end" fontSize={10} fill="#5d5f60">
            {(t * max).toFixed(max <= 1.01 ? 2 : 0)}
          </text>
        </g>
      ))}
      {values.map((v, i) => (
        <g key={i}>
          <rect x={PL + i * bw + bw * 0.2} y={y(v)} width={bw * 0.6} height={Math.max(0.5, y(0) - y(v))} fill={color} />
          <text x={PL + i * bw + bw / 2} y={y(v) - 4} textAnchor="middle" fontSize={11} fill="#131416">
            {v.toFixed(max <= 1.01 ? 3 : 1)}{suffix}
          </text>
          <text x={PL + i * bw + bw / 2} y={H - 22} textAnchor="middle" fontSize={10} fill="#5d5f60">
            {labels[i].length > 12 ? labels[i].slice(0, 12) : labels[i]}
          </text>
          {labels[i].length > 12 && (
            <text x={PL + i * bw + bw / 2} y={H - 9} textAnchor="middle" fontSize={10} fill="#5d5f60">
              {labels[i].slice(12, 24)}
            </text>
          )}
        </g>
      ))}
    </svg>
  )
}

export function RingChart({ parts, size = 150 }: { parts: { name: string; value: number; color: string }[]; size?: number }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1
  const R = 56, CX = 75, CY = 75
  let acc = 0
  const arc = (from: number, to: number) => {
    const a0 = (from / total) * 2 * Math.PI - Math.PI / 2
    const a1 = (to / total) * 2 * Math.PI - Math.PI / 2
    const large = to - from > total / 2 ? 1 : 0
    const p = (a: number, r: number) => `${CX + r * Math.cos(a)},${CY + r * Math.sin(a)}`
    return `M${p(a0, R)} A${R},${R} 0 ${large} 1 ${p(a1, R)} L${p(a1, R - 16)} A${R - 16},${R - 16} 0 ${large} 0 ${p(a0, R - 16)} Z`
  }
  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg width={size} height={size} viewBox="0 0 150 150" role="img">
        {parts.map((p, i) => {
          const d = arc(acc, acc + p.value)
          acc += p.value
          return <path key={i} d={d} fill={p.color} />
        })}
        <text x={CX} y={CY + 4} textAnchor="middle" fontSize={18} fill="#131416">{total}</text>
      </svg>
      <div>
        {parts.map((p, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginBottom: 6 }}>
            <span style={{ width: 10, height: 10, background: p.color, borderRadius: 2, display: 'inline-block' }} />
            <span>{p.name}</span>
            <span className="muted num">{p.value} · {((p.value / total) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
