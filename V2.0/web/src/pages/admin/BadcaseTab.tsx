import { useEffect, useMemo, useState } from 'react'
import { Button, Drawer, Input, Select, Space, Table, Tag, message } from 'antd'
import { api, type BadcaseRow, type BadcaseStats } from '../../api'
import { BarsChart } from '../../components/charts'

const STAGES = ['S0', 'S1', 'S2', 'S3', 'S4', 'S5', '性能', '待归因']
const NEXT: Record<string, string[]> = {
  open: ['triaged', 'dismissed'], triaged: ['linked', 'open'],
  linked: ['open'], verified: ['closed'], dismissed: ['open'], closed: [],
}
const sevColor = (s: string) => (s === 'P0' ? 'red' : s === 'P1' ? 'orange' : 'default')

export default function BadcaseTab() {
  const [rows, setRows] = useState<BadcaseRow[]>([])
  const [stats, setStats] = useState<BadcaseStats | null>(null)
  const [flt, setFlt] = useState<{ stage?: string; severity?: string; source?: string; status?: string }>({})
  const [sel, setSel] = useState<BadcaseRow | null>(null)
  const [note, setNote] = useState('')
  const [linkCase, setLinkCase] = useState('')
  const [linkIssue, setLinkIssue] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => {
    api.badcases(flt).then(setRows).catch(e => message.error(String(e)))
    api.badcaseStats().then(setStats).catch(() => {})
  }
  useEffect(load, [flt.stage, flt.severity, flt.source, flt.status])

  const doPatch = async (id: string, patch: Record<string, unknown>) => {
    setBusy(true)
    try { await api.patchBadcase(id, patch); load() } catch (e: any) { message.error(String(e.message || e)) }
    finally { setBusy(false) }
  }
  const doVerify = async (id: string) => {
    setBusy(true)
    try {
      const r = await api.verifyBadcase(id)
      message.info(r.verified ? '重跑不再触发，已置 verified' : `仍触发 ${r.after_rules}，保留 open`)
      load()
    } catch (e: any) { message.error(String(e.message || e)) }
    finally { setBusy(false) }
  }

  const stageLabels = useMemo(() => Object.keys(stats?.open_by_stage ?? {}), [stats])
  const cols = [
    { title: '严重度', width: 80, render: (_: unknown, r: BadcaseRow) => <Tag color={sevColor(r.severity)}>{r.severity}</Tag> },
    { title: '环节', width: 70, render: (_: unknown, r: BadcaseRow) => r.primary_stage },
    { title: '规则', width: 110, render: (_: unknown, r: BadcaseRow) => r.triggered_rules.map(t => t.rule_id).join(', ') },
    { title: '通道', width: 70, dataIndex: 'source' },
    { title: '状态', width: 90, dataIndex: 'status' },
    { title: 'query', render: (_: unknown, r: BadcaseRow) => <span className="small">{r.query_preview || <i className="muted">（回查：{r.scores?.item_id != null ? `dataset id${r.scores.item_id}` : '—'}）</i>}</span> },
    { title: '关联', width: 120, render: (_: unknown, r: BadcaseRow) => <span className="small muted">{r.linked_case_id || ''}{r.linked_issue_id ? ` / ${r.linked_issue_id}` : ''}</span> },
    { title: '', width: 60, render: (_: unknown, r: BadcaseRow) => <Button size="small" onClick={() => { setSel(r); setNote(''); setLinkCase(r.linked_case_id || ''); setLinkIssue(r.linked_issue_id || '') }}>处理</Button> },
  ]

  return (
    <div>
      <h3>按环节分布（open）—— 哪个环节最该升级</h3>
      <BarsChart labels={stageLabels.length ? stageLabels : ['（无 open）']}
                 values={stageLabels.map(s => stats!.open_by_stage[s])} height={160} />
      {(stats?.issue_drafts || []).map(d => (
        <div key={d.stage} className="tag warn" style={{ display: 'block', margin: '8px 0', whiteSpace: 'normal' }}>{d.draft}</div>
      ))}
      <Space style={{ margin: '16px 0' }} wrap>
        <Select allowClear placeholder="环节" style={{ width: 110 }} options={STAGES.map(s => ({ value: s, label: s }))} onChange={v => setFlt(f => ({ ...f, stage: v }))} />
        <Select allowClear placeholder="严重度" style={{ width: 100 }} options={['P0', 'P1', 'P2'].map(s => ({ value: s, label: s }))} onChange={v => setFlt(f => ({ ...f, severity: v }))} />
        <Select allowClear placeholder="通道" style={{ width: 110 }} options={['live', 'eval', 'manual'].map(s => ({ value: s, label: s }))} onChange={v => setFlt(f => ({ ...f, source: v }))} />
        <Select allowClear placeholder="状态" style={{ width: 120 }} options={['open', 'triaged', 'linked', 'verified', 'closed', 'dismissed'].map(s => ({ value: s, label: s }))} onChange={v => setFlt(f => ({ ...f, status: v }))} />
        <Button onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="badcase_id" size="small" dataSource={rows} columns={cols as any} pagination={{ pageSize: 15 }} />

      <Drawer title={sel ? `处理 ${sel.badcase_id}` : ''} open={!!sel} onClose={() => setSel(null)} width={560}>
        {sel && (
          <div>
            <div className="msg-meta" style={{ marginBottom: 12 }}>
              <Tag color={sevColor(sel.severity)}>{sel.severity}</Tag>
              <span className="tag">环节 {sel.primary_stage}</span>
              <span className="tag">{sel.source}</span>
              <span className="tag accent">{sel.status}</span>
            </div>
            <div className="muted small" style={{ marginBottom: 12 }}>{sel.query_preview}</div>
            <h4>触发规则与证据</h4>
            {sel.triggered_rules.map((t, i) => (
              <div key={i} className="small" style={{ marginBottom: 6 }}>
                <b>{t.rule_id}</b> 阈值 {JSON.stringify(t.threshold)} 实测 {JSON.stringify(t.observed)}
                <div className="muted">{t.evidence}</div>
              </div>
            ))}
            {sel.scores?.dimensions && (
              <div className="small" style={{ marginTop: 8 }}>五维分：{JSON.stringify(sel.scores.dimensions)} MOS {sel.scores.mos}</div>
            )}
            <h4 style={{ marginTop: 16 }}>改判主责环节</h4>
            <Select style={{ width: 160 }} defaultValue={sel.primary_stage}
                    options={STAGES.map(s => ({ value: s, label: s }))}
                    onChange={v => doPatch(sel.badcase_id, { primary_stage: v, note: '人工改判' })} />
            <h4 style={{ marginTop: 16 }}>关联</h4>
            <Space.Compact style={{ width: '100%' }}>
              <Input placeholder="case-XX" value={linkCase} onChange={e => setLinkCase(e.target.value)} />
              <Input placeholder="议题 v3-xx" value={linkIssue} onChange={e => setLinkIssue(e.target.value)} />
              <Button onClick={() => doPatch(sel.badcase_id, { linked_case_id: linkCase, linked_issue_id: linkIssue, note: '人工关联' })}>保存</Button>
            </Space.Compact>
            <h4 style={{ marginTop: 16 }}>note</h4>
            <Input.TextArea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="dismissed 必填；其余选填" />
            <h4 style={{ marginTop: 16 }}>状态流转（{sel.status} →）</h4>
            <Space wrap>
              {(NEXT[sel.status] || []).map(s => (
                <Button key={s} disabled={busy} onClick={() => doPatch(sel.badcase_id, { status: s, note })}>{s}</Button>
              ))}
              {sel.status === 'linked' && <Button type="primary" disabled={busy} onClick={() => doVerify(sel.badcase_id)}>回填验证（重跑 query）</Button>}
            </Space>
          </div>
        )}
      </Drawer>
    </div>
  )
}
