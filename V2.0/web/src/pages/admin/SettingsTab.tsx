import { useEffect, useState } from 'react'
import { Input, InputNumber, Select, Switch, Tag, message } from 'antd'
import { api, type Settings } from '../../api'

const KEY_FIELDS: { k: string; label: string; desc: string }[] = [
  { k: 'DOUBAO_API_KEY', label: 'DOUBAO_API_KEY', desc: '火山方舟 · 生成主链（intent 之外的所有生成调用）' },
  { k: 'TYPESAFE_API_KEY', label: 'TYPESAFE_API_KEY', desc: 'JEV · S0 意图分类' },
  { k: 'DEEPSEEK_API_KEY', label: 'DEEPSEEK_API_KEY', desc: 'DeepSeek · S3 查询扩展' },
  { k: 'QWEN_API_KEY', label: 'QWEN_API_KEY', desc: '通义千问 · judge 评审（评测与实时评分）' },
]

export default function SettingsTab() {
  const [s, setS] = useState<Settings | null>(null)
  const [saved, setSaved] = useState<Settings | null>(null)
  const [busy, setBusy] = useState(false)
  const [keys, setKeys] = useState<Record<string, { set: boolean; tail: string }>>({})
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [kBusy, setKBusy] = useState(false)
  useEffect(() => { api.settings().then(x => { setS(x); setSaved(x) }); api.keys().then(setKeys) }, [])
  if (!s) return <div className="empty-state">加载配置中…</div>
  const r = s.retrieval
  const save = async () => {
    setBusy(true)
    try {
      const out = await api.saveSettings(s)
      setSaved(out)
      message.success('已保存并生效（仅影响后续请求）')
    } catch (e: any) { message.error(String(e.message || e)) } finally { setBusy(false) }
  }
  const saveKeys = async () => {
    setKBusy(true)
    try {
      const out = await api.saveKeys(draft)
      setKeys(out)
      setDraft({})
      message.success('密钥已写入本机 .env 并即时生效')
    } catch (e: any) { message.error(String(e.message || e)) } finally { setKBusy(false) }
  }
  return (
    <div>
      <div className="section settings-grid">
        <div>
          <div className="settings-label-title">API 密钥</div>
          <div className="settings-label-desc">写入服务端本机 .env 文件并立即生效，不上传任何地方。留空表示不修改；已设置的只显示末 4 位。生成模型接入点（DOUBAO_MODEL）在下方「生成模型」改。</div>
        </div>
        <div className="card">
          {KEY_FIELDS.map(f => (
            <div className="field" key={f.k}>
              <div className="field-label">{f.label} {keys[f.k]?.set
                ? <Tag color="green" style={{ marginLeft: 6 }}>已设置 ****{keys[f.k].tail}</Tag>
                : <Tag style={{ marginLeft: 6 }}>未设置</Tag>}</div>
              <Input.Password
                placeholder={keys[f.k]?.set ? '不修改请留空' : '粘贴密钥后点下方保存'}
                value={draft[f.k] || ''}
                onChange={e => setDraft({ ...draft, [f.k]: e.target.value })} />
              <div className="muted small" style={{ marginTop: 4 }}>{f.desc}</div>
            </div>
          ))}
          <button className="btn btn-primary" onClick={saveKeys} disabled={kBusy || !Object.values(draft).some(v => v.trim())}>保存密钥</button>
        </div>
      </div>
      <div className="section settings-grid">
        <div>
          <div className="settings-label-title">模型配置</div>
          <div className="settings-label-desc">意图分类固定为 JEV（typesafe_sdk），生成走火山方舟或 DeepSeek，judge 走 Qwen。实时 judge 默认关闭：它会为每次回答增加一次评审调用与约 10 秒延迟。</div>
        </div>
        <div className="card">
          <div className="field">
            <div className="field-label">意图分类模型</div>
            <Select style={{ width: '100%' }} value={s.models.intent} options={[{ value: 'jev-1.13.0', label: 'jev-1.13.0' }]} onChange={v => setS({ ...s, models: { ...s.models, intent: v } })} />
          </div>
          <div className="field">
            <div className="field-label">生成模型</div>
            <Select style={{ width: '100%' }} value={s.models.generation}
              options={[...new Set([s.models.generation, 'doubao-pro-32k-240828', 'deepseek-chat'])].map(v => ({ value: v, label: v }))}
              onChange={v => setS({ ...s, models: { ...s.models, generation: v } })} />
            <div className="muted small" style={{ marginTop: 4 }}>方舟填接入点 ID（ep- 开头），从 .env 的 DOUBAO_MODEL 读取为默认值。</div>
          </div>
          <div className="field">
            <div className="field-label">judge 模型</div>
            <Select style={{ width: '100%' }} value={s.models.judge}
              options={['qwen-plus', 'qwen-max'].map(v => ({ value: v, label: v }))}
              onChange={v => setS({ ...s, models: { ...s.models, judge: v } })} />
          </div>
          <div className="field">
            <span className="field-label" style={{ marginRight: 12 }}>回答后实时 judge 评分</span>
            <Switch checked={s.judge_live} onChange={v => setS({ ...s, judge_live: v })} />
          </div>
        </div>
      </div>
      <div className="section settings-grid">
        <div>
          <div className="settings-label-title">检索与 ReAct 参数</div>
          <div className="settings-label-desc">
            默认值为当前冻结口径：top-10、lane 20、RRF k=60、追加轮上限 5、门控阈值 0.9。
            修改会写入服务端并作用于后续请求；历史评测结果不受影响。veto 是评测侧的对抗一票否决口径开关，不改变线上检索行为。
          </div>
        </div>
        <div className="card">
          <div className="grid-2">
            <div className="field"><div className="field-label">top_k</div><InputNumber min={1} max={30} value={r.topk} onChange={v => setS({ ...s, retrieval: { ...r, topk: v ?? 10 } })} /></div>
            <div className="field"><div className="field-label">lane_fetch</div><InputNumber min={5} max={50} value={r.lane_fetch} onChange={v => setS({ ...s, retrieval: { ...r, lane_fetch: v ?? 20 } })} /></div>
            <div className="field"><div className="field-label">RRF k</div><InputNumber min={1} max={200} value={r.rrf_k} onChange={v => setS({ ...s, retrieval: { ...r, rrf_k: v ?? 60 } })} /></div>
            <div className="field"><div className="field-label">最大追加轮数</div><InputNumber min={0} max={8} value={r.react_max_rounds} onChange={v => setS({ ...s, retrieval: { ...r, react_max_rounds: v ?? 5 } })} /></div>
            <div className="field"><div className="field-label">充分性门控阈值（sufficient）</div><InputNumber min={0} max={1} step={0.05} value={r.suff_th} onChange={v => setS({ ...s, retrieval: { ...r, suff_th: v ?? 0.9 } })} /></div>
            <div className="field"><div className="field-label">错误前提阈值（false_premise）</div><InputNumber min={0} max={1} step={0.05} value={r.fp_th} onChange={v => setS({ ...s, retrieval: { ...r, fp_th: v ?? 0.5 } })} /></div>
          </div>
          <div className="field">
            <span className="field-label" style={{ marginRight: 12 }}>对抗 veto（评测口径）</span>
            <Switch checked={r.veto_enabled} onChange={v => setS({ ...s, retrieval: { ...r, veto_enabled: v } })} />
          </div>
        </div>
      </div>
      <button className="btn btn-primary" onClick={save} disabled={busy}>保存并生效</button>
      {saved && (
        <div className="section" style={{ marginTop: 24 }}>
          <div className="section-head"><h3>当前生效配置快照（只读）</h3></div>
          <div className="snapshot">{JSON.stringify(saved, null, 2)}</div>
        </div>
      )}
    </div>
  )
}
