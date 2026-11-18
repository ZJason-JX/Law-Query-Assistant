import { useCallback, useEffect, useState } from 'react'
import { Drawer, Input, Popconfirm, Select, Table, Tabs, message } from 'antd'
import { api, type Chunk } from '../../api'

const LAWS = ['民法典', '公司法', '反不正当竞争法', '消费者权益保护法', '劳动法', '劳动合同法']
const empty: Partial<Chunk> = { law: '民法典', status: '现行有效', text: '', article_no: '', id: '' }

function ChunkEditor({ chunk, onClose, onSaved }: { chunk: Partial<Chunk> | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<Partial<Chunk>>(empty)
  const isNew = !chunk?.text
  useEffect(() => { if (chunk) setForm(chunk) }, [chunk])
  if (!chunk) return null
  const save = async () => {
    try {
      if (isNew) await api.createChunk(form)
      else await api.updateChunk(chunk.id!, form)
      message.success('已保存：chunks.jsonl / SQLite / Qdrant 三处同步，并写入审计日志')
      onSaved()
    } catch (e: any) { message.error(String(e.message || e)) }
  }
  return (
    <Drawer title={isNew ? '新增法条' : `编辑 ${chunk.law} ${chunk.article_no}`} open onClose={onClose} width={560}>
      <div className="field"><div className="field-label">chunk id（不可改）</div>
        <Input value={form.id} disabled={!isNew} onChange={e => setForm({ ...form, id: e.target.value })} placeholder="如 civil-law-999" /></div>
      <div className="field"><div className="field-label">所属法律</div>
        <Select style={{ width: '100%' }} value={form.law} options={LAWS.map(l => ({ value: l, label: l }))} onChange={v => setForm({ ...form, law: v })} /></div>
      <div className="field"><div className="field-label">条号</div>
        <Input value={form.article_no} onChange={e => setForm({ ...form, article_no: e.target.value })} placeholder="第571条" /></div>
      <div className="field"><div className="field-label">章节</div>
        <Input value={form.chapter} onChange={e => setForm({ ...form, chapter: e.target.value })} /></div>
      <div className="field"><div className="field-label">效力状态</div>
        <Select style={{ width: '100%' }} value={form.status}
          options={['现行有效', '历史版本', '尚未生效', '已废止'].map(v => ({ value: v, label: v }))}
          onChange={v => setForm({ ...form, status: v })} /></div>
      <div className="field"><div className="field-label">正文</div>
        <Input.TextArea rows={12} value={form.text} onChange={e => setForm({ ...form, text: e.target.value })} /></div>
      <button className="btn btn-primary" onClick={save}>保存</button>
      <div className="muted small" style={{ marginTop: 10 }}>保存会重新嵌入该条正文并同步向量库；原值写入审计日志。</div>
    </Drawer>
  )
}

function LawsTable() {
  const [law, setLaw] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ total: number; items: Chunk[] }>({ total: 0, items: [] })
  const [editing, setEditing] = useState<Partial<Chunk> | null>(null)
  const load = useCallback(async () => {
    const d = await api.laws(law, search, page)
    setData(d)
  }, [law, search, page])
  useEffect(() => { load().catch(e => message.error(String(e))) }, [load])
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Select style={{ width: 220 }} value={law} onChange={v => { setLaw(v); setPage(1) }}
          options={[{ value: '', label: '全部法律' }, ...LAWS.map(l => ({ value: l, label: l }))]} />
        <Input.Search style={{ width: 320 }} placeholder="搜索条号 / 关键词 / chunk id" allowClear
          onSearch={v => { setSearch(v); setPage(1) }} />
        <button className="btn btn-primary" onClick={() => setEditing({ ...empty })}>新增法条</button>
      </div>
      <Table
        rowKey="id" size="small" dataSource={data.items}
        pagination={{ current: page, total: data.total, pageSize: 20, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        columns={[
          { title: '法律', dataIndex: 'law', width: 150 },
          { title: '条号', dataIndex: 'article_no', width: 100 },
          { title: '章节', dataIndex: 'chapter', width: 200, render: v => v || '—' },
          { title: '状态', dataIndex: 'status', width: 100 },
          { title: '正文预览', dataIndex: 'text', render: (v: string, r: Chunk) => (
            <a onClick={async () => setEditing(await api.law(r.id))}>{v}…</a>) },
          { title: '操作', width: 120, render: (_: any, r: Chunk) => (
            <span>
              <a onClick={async () => setEditing(await api.law(r.id))}>编辑</a>
              <Popconfirm title={'确认删除 ' + r.law + r.article_no + '？'} description="会同步删除向量库与 SQLite 记录，原值写入审计。"
                onConfirm={async () => { await api.deleteChunk(r.id); message.success('已删除并记录审计'); load() }}>
                <a style={{ color: 'var(--negative)', marginLeft: 12 }}>删除</a>
              </Popconfirm>
            </span>
          ) },
        ]}
      />
      {editing && <ChunkEditor chunk={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
    </div>
  )
}

function AuditTable() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api.audit().then(setRows).catch(e => message.error(String(e))) }, [])
  return (
    <Table
      rowKey={(r: any) => `${r.ts}-${r.chunk_id}-${r.action}`} size="small" dataSource={rows}
      pagination={{ pageSize: 15 }}
      columns={[
        { title: '时间', dataIndex: 'ts', width: 180, render: (t: number) => new Date(t * 1000).toLocaleString('zh-CN') },
        { title: '操作', dataIndex: 'action', width: 90, render: (a: string) => (
          <span className={`tag ${a === 'delete' ? 'negative' : a === 'create' ? 'positive' : 'accent'}`}>{a}</span>) },
        { title: 'chunk id', dataIndex: 'chunk_id', width: 220 },
        { title: '原值 → 新值', render: (_: any, r: any) => (
          <details>
            <summary>展开差异</summary>
            <div className="grid-2" style={{ marginTop: 8 }}>
              <pre className="snapshot" style={{ maxHeight: 300, overflow: 'auto' }}>{r.old_value ? JSON.stringify(r.old_value, null, 2) : '（无）'}</pre>
              <pre className="snapshot" style={{ maxHeight: 300, overflow: 'auto' }}>{r.new_value ? JSON.stringify(r.new_value, null, 2) : '（已删除）'}</pre>
            </div>
          </details>
        ) },
      ]}
      locale={{ emptyText: '暂无编辑记录。对知识库的新增、编辑、删除都会在这里留下原值与新值。' }}
    />
  )
}

export default function LawsTab() {
  return (
    <Tabs items={[
      { key: 'list', label: '法条列表', children: <LawsTable /> },
      { key: 'audit', label: '审计日志', children: <AuditTable /> },
    ]} />
  )
}
