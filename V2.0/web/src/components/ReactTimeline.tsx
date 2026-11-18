import type { ArticleHit, CitationRow, TlEvent } from '../api'

function ArtTable({ arts, onOpenChunk }: { arts: ArticleHit[]; onOpenChunk: (id: string) => void }) {
  if (!arts?.length) return <div className="muted small">（本轮未返回条号明细）</div>
  return (
    <table className="art-table">
      <tbody>
        {arts.map(a => (
          <tr key={a.id}>
            <td>
              <button className="art-link" onClick={() => onOpenChunk(a.id)}>
                {a.law.replace('中华人民共和国', '')}{a.article_no}
              </button>
            </td>
            <td className="num">
              {a.rrf != null ? `rrf ${a.rrf.toFixed(3)}` : ''}
              {a.dense_rank ? ` · d#${a.dense_rank}` : ''}{a.sparse_rank ? ` · s#${a.sparse_rank}` : ''}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Gate({ e }: { e: TlEvent }) {
  const hot = (e.false_premise ?? 0) > (e.fp_threshold ?? 0.5)
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="num small">
        第 {e.round + 1} 次门控：sufficient = <b>{e.sufficient}</b>
        {e.false_premise != null && <> · false_premise = <b style={{ color: hot ? 'var(--negative)' : undefined }}>{e.false_premise}</b></>}
        {' '}<span className={`tag ${e.decision === 'stop' ? 'positive' : 'warn'}`}>{e.decision === 'stop' ? '通过，直接生成' : '不足，追加检索'}</span>
      </div>
      <div className="gate-bar"><div className={`gate-fill ${hot ? 'hot' : ''}`} style={{ width: `${Math.min(100, (e.sufficient ?? 0) * 100)}%` }} /></div>
    </div>
  )
}

const STAGES = [
  { id: 'S0', name: 'S0 意图路由', desc: 'JEV 分类意图与错误前提' },
  { id: 'S1', name: 'S1 首轮检索', desc: 'dense + sparse 八路 RRF' },
  { id: 'S2', name: 'S2 充分性门控', desc: '证据足够才放行，否则进循环' },
  { id: 'S3', name: 'S3 追加轮', desc: 'DeepSeek 缺口查询补检' },
  { id: 'S4', name: 'S4 生成', desc: '按意图模板生成回答' },
  { id: 'S5', name: 'S5 引用校验', desc: '确定性审计：引用必须落在上下文内' },
]

export function ReactTimeline({ events, subtitle, running, onOpenChunk }: {
  events: TlEvent[]
  subtitle?: string
  running: boolean
  onOpenChunk: (id: string) => void
}) {
  const byStage = (s: string) => events.filter(e => e.stage === s)
  const lastStage = events.length ? events[events.length - 1].stage : null
  const s5 = byStage('S5')[0]
  const citations: CitationRow[] = s5?.citations ?? []

  return (
    <div className="react-panel">
      <div className="react-head">
        <h2>ReAct 状态机</h2>
        <div className="muted small" style={{ marginTop: 4 }}>S0 → S5，由后端 SSE 事件实时点亮</div>
      </div>
      <div className="react-body">
        {subtitle && <div className="subtitle-banner">{subtitle}</div>}
        {!events.length && <div className="empty-state">发送一个问题，这里会逐步展示检索、门控与引用校验过程。</div>}
        {STAGES.map(s => {
          const es = byStage(s.id)
          const state = es.length ? 'done' : running ? (lastStage && STAGES.findIndex(x => x.id === lastStage) >= STAGES.findIndex(x => x.id === s.id) ? 'active' : '') : ''
          return (
            <div className={`tl-node ${state}`} key={s.id}>
              <span className="tl-dot" />
              <div className="tl-title">{s.name}<span className="muted small">{s.desc}</span></div>
              {es.length > 0 && (
                <div className="tl-detail">
                  {s.id === 'S0' && (
                    <div className="msg-meta">
                      <span className="tag accent">{es[0].intent}</span>
                      <span className="tag num">conf {es[0].confidence}</span>
                      {es[0].false_premise != null && <span className={`tag num ${es[0].false_premise > 0.5 ? 'negative' : ''}`}>fp {es[0].false_premise}</span>}
                    </div>
                  )}
                  {s.id === 'S1' && (
                    <>
                      {es[0].trap_missing && <div className="tag warn" style={{ marginBottom: 4 }}>trap 主条 {es[0].trap_missing} 不在首轮 top-10</div>}
                      <ArtTable arts={es[0].articles} onOpenChunk={onOpenChunk} />
                    </>
                  )}
                  {s.id === 'S2' && es.map((e, i) => <Gate key={i} e={e} />)}
                  {s.id === 'S3' && es.map((e, i) => (
                    <div key={i} style={{ marginBottom: 10 }}>
                      {e.new_query && (
                        <div className="small" style={{ marginBottom: 4 }}>
                          <b>第 {e.round} 轮</b> · 新增 {e.recalled_delta} 条
                          <div className="muted" style={{ marginTop: 2 }}>缺口查询：{e.new_query}</div>
                        </div>
                      )}
                      {e.trap_recovered && <div className="tag positive" style={{ marginBottom: 4 }}>已补回 trap 主条 {e.trap_recovered}</div>}
                      {e.articles?.length > 0 && (
                        <details className="tl-exp">
                          <summary>本轮 top-10 明细</summary>
                          <ArtTable arts={e.articles} onOpenChunk={onOpenChunk} />
                        </details>
                      )}
                    </div>
                  ))}
                  {s.id === 'S4' && <div className="small">生成中（{es[0].prompt_file || '意图模板'}）…</div>}
                  {s.id === 'S5' && s5 && (
                    <div>
                      <div className="msg-meta" style={{ marginBottom: 6 }}>
                        <span className="tag num">引用 {s5.n} 条</span>
                        <span className={`tag num ${s5.ungrounded ? 'negative' : 'positive'}`}>ungrounded {s5.ungrounded}</span>
                      </div>
                      {citations.map((c, i) => (
                        <div key={i} className="small" style={{ display: 'flex', gap: 6, marginBottom: 4, alignItems: 'baseline' }}>
                          <span className={`tag ${c.in_context ? 'positive' : 'negative'}`}>{c.band}</span>
                          <span>{c.law.replace('中华人民共和国', '')}{c.article_no}</span>
                          {c.quote_ratio != null && <span className="muted num">{c.quote_ratio}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
