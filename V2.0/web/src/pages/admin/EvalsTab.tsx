import { useEffect, useState } from 'react'
import { Table } from 'antd'
import { api } from '../../api'
import { BarsChart, LineChart } from '../../components/charts'

const DIMS = ['准确性', '相关性', '完整性', '简洁性', '安全性']
const LABELS: Record<string, string> = {
  v0_rag_baseline: 'v0 朴素基线',
  'v0.1_embed_rich': 'v0.1 富文本嵌入',
  'v0.2_rerank': 'v0.2 精排',
  'v0.3_query_exp': 'v0.3 查询扩展',
  'v0.4_expand_rerank': 'v0.4 扩展+精排',
  'v0.5_alias': 'v0.5 别名表',
  'v0.6_rrf': 'v0.6 RRF',
  'v0.6_rrf_alias': 'v0.6 RRF+别名（冻结）',
  dataset_v2_baseline_primary: 'v2 基线',
  v20_react: 'ReAct v2.0',
  v25_react_5r_w: 'v2.1 降权',
  v27_react_cap: 'v2.1 法域上限',
  v28_react_cap_w6: 'v2.1 定稿',
}
const shortVer = (v: string) => LABELS[v] ?? v

function GenTable({ rows, title }: { rows: any[]; title: string }) {
  return (
    <Table
      rowKey="version" size="small" dataSource={rows} pagination={false}
      title={() => <b>{title}</b>}
      columns={[
        { title: '版本', dataIndex: 'version', width: 200 },
        { title: 'MOS', dataIndex: 'mos', width: 90, render: (v: number) => <b className="num">{v?.toFixed(3)}</b> },
        ...DIMS.map(d => ({ title: d, dataIndex: d, render: (v: number) => <span className="num">{v?.toFixed(2)}</span> })),
      ]}
    />
  )
}

export default function EvalsTab() {
  const [d, setD] = useState<any>(null)
  useEffect(() => { api.evals().then(setD) }, [])
  if (!d) return <div className="empty-state">读取落盘评测结果…</div>
  const ab = d.retrieval_ablation
  return (
    <div>
      <div className="section">
        <div className="section-head">
          <h2>检索消融：v0 → v0.6-RRF</h2>
          <div className="section-sub">七个版本的显性 / 隐性事实命中率（primary recall@10），来自 evals/results 各版 recall_report.json。</div>
        </div>
        <div className="card">
          <div className="msg-meta" style={{ marginBottom: 8 }}>
            <span className="tag" style={{ color: '#1b6c80' }}>— 显性事实</span>
            <span className="tag" style={{ color: '#2f70bb' }}>— 隐性事实</span>
          </div>
          <LineChart
            points={ab.map((x: any) => shortVer(x.version))}
            series={[
              { name: '显性', color: '#1b6c80', values: ab.map((x: any) => x.explicit) },
              { name: '隐性', color: '#2f70bb', values: ab.map((x: any) => x.implicit) },
            ]}
            yMax={1} yLabel="recall@10"
          />
        </div>
      </div>
      <div className="grid-2 section">
        <div className="card">
          <div className="section-head"><h3>ReAct 检索演进（overall primary recall）</h3></div>
          <BarsChart
            labels={d.react_recall.map((x: any) => shortVer(x.version))}
            values={d.react_recall.map((x: any) => x.overall ?? 0)}
            yMax={1}
          />
        </div>
        <div className="card">
          <div className="section-head"><h3>意图分类准确率</h3></div>
          <BarsChart labels={d.intent.map((x: any) => x.label)} values={d.intent.map((x: any) => x.accuracy)} yMax={1} />
          <div className="muted small">旧口径来自冻结的 v2 意图缓存；新标准为当前 JEV 标签标准，同集调参，数值偏乐观。</div>
        </div>
      </div>
      <div className="section">
        <div className="section-head">
          <h2>生成侧版本对比</h2>
          <div className="section-sub">v1.0 → v1.1 → v1.2 为单轮回路；v21 起为 ReAct 端到端（含线上与意图缓存口径）。</div>
        </div>
        <GenTable rows={d.generation} title="单轮生成（冻结基线）" />
        <div style={{ height: 16 }} />
        <GenTable rows={d.react_e2e} title="ReAct 端到端" />
      </div>
      <div className="section">
        <div className="section-head">
          <h2>引用审计</h2>
          <div className="section-sub">ungrounded = 引用条号不在该次检索上下文内。所有已审计版本均为 0；unmatched 指引用在上下文内但引文改写失真。</div>
        </div>
        <Table
          rowKey="version" size="small" dataSource={d.citations} pagination={false}
          columns={[
            { title: '版本', dataIndex: 'version', width: 210 },
            { title: '引用条数', dataIndex: 'n', width: 100, render: (v: number) => <span className="num">{v}</span> },
            { title: 'ungrounded', dataIndex: 'ungrounded', width: 130, render: (v: number) => <span className={`tag ${v ? 'negative' : 'positive'}`}>{v}</span> },
            { title: 'verbatim / paraphrase / unmatched', render: (_: any, r: any) => (
              <span className="num">{r.bands.verbatim ?? 0} / {r.bands.paraphrase ?? 0} / {r.bands.unmatched ?? 0}</span>) },
          ]}
        />
      </div>
    </div>
  )
}
