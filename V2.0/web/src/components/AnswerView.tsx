import { useState } from 'react'
import { Drawer, Spin } from 'antd'
import { api, type AnswerPayload, type Chunk, type CitationRow } from '../api'
import { abbr, citKey, splitAnswer } from './citutil'

export function useChunkDrawer() {
  const [chunk, setChunk] = useState<Chunk | null>(null)
  const [loading, setLoading] = useState(false)
  const open = async (id: string) => {
    setLoading(true)
    setChunk({ id } as Chunk)
    try { setChunk(await api.law(id)) } finally { setLoading(false) }
  }
  const drawer = (
    <Drawer title={chunk && chunk.law ? `${chunk.law} ${chunk.article_no}` : '法条详情'}
            open={!!chunk} onClose={() => setChunk(null)} width={520}>
      {loading ? <Spin /> : chunk && (
        <div>
          <div className="msg-meta" style={{ marginBottom: 14 }}>
            <span className="tag">{chunk.status || '现行有效'}</span>
            {chunk.chapter && <span className="tag">{chunk.chapter}</span>}
            {chunk.version && <span className="tag">{chunk.version}</span>}
          </div>
          <div style={{ lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>{chunk.text}</div>
          <div className="muted small" style={{ marginTop: 16 }}>chunk id：{chunk.id}</div>
        </div>
      )}
    </Drawer>
  )
  return { open, drawer }
}

const INLINE_RE = /《([^》]+)》第([0-9一二三四五六七八九十百千零]+)条/g

/** 正文内联《法》第N条 → 上标可点击 chip；末尾引用块剥离成清单 */
export function AnswerView({ payload, citations, onOpenChunk }: {
  payload: AnswerPayload
  citations?: CitationRow[]
  onOpenChunk: (id: string) => void
}) {
  const { body, citations: parsed } = splitAnswer(payload.answer)
  const auditByKey = new Map((citations || []).map(c => [citKey(c.law, c.article_no), c]))
  const idByKey = new Map<string, string>()
  for (const c of citations || []) if (c.chunk_id) idByKey.set(citKey(c.law, c.article_no), c.chunk_id)

  const openFor = (law: string, art: string) => {
    const id = idByKey.get(citKey(law, art))
    if (id) onOpenChunk(id)
  }
  const parts: React.ReactNode[] = []
  let last = 0, k = 0
  for (const m of body.matchAll(INLINE_RE)) {
    const i = m.index!
    if (i > last) parts.push(body.slice(last, i))
    const [, law, art] = m
    const full = `${law}第${art}条`
    const id = idByKey.get(citKey(law, art))
    parts.push(
      <span key={k++}>
        {full}
        <button className="cit-chip" onClick={() => openFor(law, art)}
                title={id ? '查看法条原文' : '该条未在本轮引用清单中'}>
          {abbr(law)}{art}
        </button>
      </span>
    )
    last = i + m[0].length
  }
  parts.push(body.slice(last))

  return (
    <div>
      <div className="msg-answer">{parts}</div>
      {(parsed.length > 0 || (citations || []).length > 0) && (
        <div style={{ marginTop: 12 }}>
          <div className="muted small" style={{ marginBottom: 6 }}>本次引用法条</div>
          <div className="msg-meta">
            {parsed.map((c, i) => {
              const key = citKey(c.law, c.article_no)
              const a = auditByKey.get(key)
              const id = idByKey.get(key)
              return (
                <button key={i} className={`tag ${a ? (a.in_context ? 'positive' : 'negative') : 'accent'}`}
                        style={{ border: 'none', cursor: id ? 'pointer' : 'default' }}
                        onClick={() => id && onOpenChunk(id)}
                        title={a ? `${a.band}${a.quote_ratio != null ? ` · 保真度 ${a.quote_ratio}` : ''}` : ''}>
                  {c.law.replace('中华人民共和国', '')}{c.article_no}
                  {a && !a.in_context ? ' · 越界' : ''}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
