import { useEffect, useRef, useState } from 'react'
import { Radio } from 'antd'
import { api, streamChat, type AnswerPayload, type BadcaseBadge, type CitationRow, type TlEvent } from '../api'
import { AnswerView, useChunkDrawer } from '../components/AnswerView'
import { ReactTimeline } from '../components/ReactTimeline'

/** 坏例红色角标 + 点击展开归因卡（演示模式无 badcases 字段，自然不显示） */
function BadcaseTag({ bc }: { bc: BadcaseBadge }) {
  const [open, setOpen] = useState(false)
  return (
    <span style={{ display: 'inline-block' }}>
      <button className="tag negative" style={{ cursor: 'pointer', border: 'none' }}
              onClick={() => setOpen(o => !o)}>
        坏例 {bc.severity} · {bc.rules.join('/')}
      </button>
      {open && (
        <div className="tag" style={{ display: 'block', marginTop: 6, whiteSpace: 'normal', lineHeight: 1.7 }}>
          <div>主责环节 <b>{bc.primary_stage}</b> · 状态 {bc.status} · {bc.badcase_id}</div>
          {bc.triggered_rules.map((t, i) => (
            <div key={i} className="small muted">
              {t.rule_id} 阈值 {JSON.stringify(t.threshold)} 实测 {JSON.stringify(t.observed)} — {t.evidence}
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

const DEMO_QUERY = '员工不辞而别就算自动离职、无需任何手续，那公司在试用期直接让他走并说明理由总没问题吧？'
const EXAMPLES = [
  { title: '对抗样本：错误前提纠正（演示同款）', q: DEMO_QUERY },
  { title: '法条精准检索：法定代表人与 30 日期限', q: '我们公司的法定代表人是由执行公司事务的董事兼任的，现在这位董事已经提交了辞任书，请问他的法定代表人身份是不是也随之辞去了？公司必须在多长时间内确定新的法定代表人？' },
  { title: '复合问题：跨公司法与民法典', q: '我是一家股份有限公司的小股东，持股比例超过百分之十，已经连续持股一百多天，现在董事会和监事会都不愿意召集临时股东会，我想自己召集，但之前我向公司发出过一份希望召开股东会的要约，对方承诺后我又反悔想撤销，撤销通知在对方承诺之后才到达，这两件事分别怎么处理？' },
]

interface Msg {
  role: 'user' | 'assistant'
  text?: string
  payload?: AnswerPayload
  citations?: CitationRow[]
  events?: TlEvent[]
}

export default function ChatPage({ demo, setDemo }: { demo: boolean; setDemo: (v: boolean) => void }) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<TlEvent[]>([])
  const [subtitle, setSubtitle] = useState('')
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [thumbed, setThumbed] = useState<Set<number>>(new Set())
  const auditRef = useRef<CitationRow[]>([])
  const { open, drawer } = useChunkDrawer()

  useEffect(() => {
    let sid = localStorage.getItem('lqa_sid')
    if (!sid) {
      sid = crypto.randomUUID()
      localStorage.setItem('lqa_sid', sid)
    }
    setSessionId(sid)
  }, [])

  // 刷新恢复：按 session_id 拉回该会话全部可展示轮
  useEffect(() => {
    if (!sessionId) return
    api.turns(sessionId).then(rows => {
      const restored: Msg[] = []
      for (const t of rows) {
        restored.push({ role: 'user', text: t.user_query })
        restored.push({
          role: 'assistant',
          payload: {
            answer: t.answer, retrieved_ids: t.retrieved_law_ids.map(r => r.chunk_id),
            intent: t.intent_label ?? undefined, judge: t.judge_scores, turn_no: t.turn_no,
          },
          citations: t.citations,
        })
      }
      setMessages(restored)
    }).catch(() => {})
  }, [sessionId])

  const newSession = () => {
    const sid = crypto.randomUUID()
    localStorage.setItem('lqa_sid', sid)
    setSessionId(sid)
    setMessages([])
    setEvents([])
    setSubtitle('')
    setError('')
    auditRef.current = []
  }

  const submit = async (q: string) => {
    if (!q.trim() || running) return
    setError('')
    setRunning(true)
    setEvents([])
    setSubtitle('')
    auditRef.current = []
    setMessages(m => [...m, { role: 'user', text: q }])
    const runEvents: TlEvent[] = []
    try {
      await streamChat(q, demo, sessionId, {
        onState: e => {
          runEvents.push(e)
          if (e.stage === 'S5') auditRef.current = e.citations ?? []
          setEvents([...runEvents])
        },
        onSubtitle: setSubtitle,
        onAnswer: payload => {
          setMessages(m => [...m, {
            role: 'assistant', payload,
            citations: auditRef.current, events: [...runEvents],
          }])
        },
        onError: msg => setError(msg),
      })
    } catch (e: any) {
      setError(String(e.message || e))
    } finally {
      setRunning(false)
      setInput('')
    }
  }

  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
  const shownEvents = events.length ? events : lastAssistant?.events ?? []

  return (
    <div className="chat-grid">
      <div className="chat-col">
        <div className="chat-scroll">
          {!messages.length && (
            <div className="chat-empty">
              <h1>问一个法律问题，看系统怎么思考</h1>
              <div className="page-sub">
                知识库为民法典、公司法、反不正当竞争法（2025 修订）、消费者权益保护法、劳动法与劳动合同法，共 1868 条。
                右侧会实时展示 S0 意图路由到 S5 引用校验的完整过程。回答仅供参考，不构成法律意见。
              </div>
              {EXAMPLES.map(e => (
                <button key={e.title} className="example-chip" onClick={() => setInput(e.q)}>
                  <b>{e.title}</b>
                  <div className="muted small" style={{ marginTop: 4 }}>{e.q.slice(0, 64)}…</div>
                </button>
              ))}
            </div>
          )}
          {messages.map((m, i) => (
            <div className="msg" key={i}>
              <div className="msg-role">{m.role === 'user' ? '提问' : '回答'}</div>
              {m.role === 'user' ? (
                <div className="msg-user-text">{m.text}</div>
              ) : m.payload && (
                <>
                  <AnswerView payload={m.payload} citations={m.citations} onOpenChunk={open} />
                  <div className="msg-meta">
                    {m.payload.turn_no && <span className="tag">第{m.payload.turn_no}轮</span>}
                    {m.payload.intent && <span className="tag accent">意图 {m.payload.intent}{m.payload.confidence != null ? ` · ${m.payload.confidence}` : ''}</span>}
                    {m.payload.judge && <span className="tag positive">judge MOS {m.payload.judge.mos.toFixed(1)}</span>}
                    {m.payload.latency_ms != null && <span className="tag num">{(m.payload.latency_ms / 1000).toFixed(1)}s</span>}
                    {m.payload.demo && <span className="tag">演示重放</span>}
                    {m.payload.mock && <span className="tag warn">演示数据（MOCK）</span>}
                    {(m.payload.badcases || []).map(bc => <BadcaseTag key={bc.badcase_id} bc={bc} />)}
                    {!m.payload.demo && !m.payload.mock && m.payload.turn_no && !thumbed.has(i) && (
                      <button className="tag" style={{ cursor: 'pointer', border: 'none' }}
                              title="标记为坏例（人工通道）"
                              onClick={async () => {
                                await api.thumbDown(sessionId, m.payload!.turn_no!)
                                setThumbed(s => new Set(s).add(i))
                              }}>点踩</button>
                    )}
                    {thumbed.has(i) && <span className="tag warn">已标记坏例</span>}
                  </div>
                </>
              )}
            </div>
          ))}
          {running && <div className="muted small">链路运行中，右侧状态机实时推进…</div>}
          {error && <div className="tag negative" style={{ padding: 8 }}>出错：{error}</div>}
        </div>
        <div className="composer">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <button className="btn" onClick={newSession} disabled={running}>新建对话</button>
            <span className="muted small">
              第 {Math.max(1, messages.filter(m => m.role === 'user').length + (running ? 0 : 1))} 轮 · 上下文在同一会话内累积
            </span>
          </div>
          <textarea
            placeholder={demo ? '演示模式：点击下方按钮重放 id29 五幕动线' : '输入法律问题，Enter 发送，Shift+Enter 换行'}
            value={demo ? DEMO_QUERY : input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit(demo ? DEMO_QUERY : input)
              }
            }}
            disabled={demo || running}
          />
          <button className="btn btn-primary" onClick={() => submit(demo ? DEMO_QUERY : input)} disabled={running}>
            {running ? '运行中…' : demo ? (messages.length ? '重放五幕' : '开始演示') : '发送'}
          </button>
        </div>
      </div>
      <ReactTimeline events={shownEvents} subtitle={subtitle} running={running} onOpenChunk={open} />
      {drawer}
    </div>
  )
}
