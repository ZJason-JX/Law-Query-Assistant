import { useEffect, useState } from 'react'
import { api } from '../../api'
import { LineChart, RingChart } from '../../components/charts'

const INTENT_COLORS: Record<string, string> = {
  elements_liability: '#1b6c80', statute_lookup: '#2f70bb', rule_conflict: '#a86f0c',
  concept_definition: '#1e7b4f', irrelevant: '#5d5f60', other: '#cdced1', unknown: '#cdced1',
}

export default function UsageTab() {
  const [u, setU] = useState<any>(null)
  useEffect(() => { api.usage().then(setU) }, [])
  if (!u) return <div className="empty-state">统计中…</div>
  if (!u.total) {
    return (
      <div className="empty-state">
        暂无真实请求记录。到对话页发送一个真实问题（非演示重放）后，这里会出现累计查询、门控触发率、延迟分布与引用审计计数。
        {u.mock_only && <div className="watermark" style={{ marginTop: 8 }}>当前仅有 MOCK 演示数据，不计入真实用量。</div>}
      </div>
    )
  }
  return (
    <div>
      <div className="section card">
        <div className="kpi-strip">
          <div><div className="kpi-label">累计真实查询</div><div className="kpi-value num">{u.total}<span className="unit">次</span></div></div>
          <div><div className="kpi-label">门控触发追加轮比例</div><div className="kpi-value num">{(u.gate.trigger_rate * 100).toFixed(0)}<span className="unit">%</span></div></div>
          <div><div className="kpi-label">平均追加轮数</div><div className="kpi-value num">{u.gate.avg_rounds}</div></div>
          <div><div className="kpi-label">延迟 P50</div><div className="kpi-value num">{(u.latency.p50_ms / 1000).toFixed(1)}<span className="unit">s</span></div></div>
          <div><div className="kpi-label">延迟 P95</div><div className="kpi-value num">{(u.latency.p95_ms / 1000).toFixed(1)}<span className="unit">s</span></div></div>
          <div><div className="kpi-label">累计引用 / ungrounded</div>
            <div className="kpi-value num">{u.citations.total}<span className="unit">/ {u.citations.ungrounded}</span></div></div>
        </div>
      </div>
      <div className="grid-2 section">
        <div className="card">
          <div className="section-head"><h3>按日查询量</h3></div>
          <LineChart points={u.per_day.map((x: any) => x.day)}
            series={[{ name: '查询', color: '#1b6c80', values: u.per_day.map((x: any) => x.n) }]} />
        </div>
        <div className="card">
          <div className="section-head"><h3>意图分布</h3></div>
          <RingChart parts={Object.entries(u.intents).map(([k, v]) => ({ name: k, value: v as number, color: INTENT_COLORS[k] || '#2f70bb' }))} />
        </div>
      </div>
    </div>
  )
}
