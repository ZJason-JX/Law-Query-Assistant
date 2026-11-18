export interface ArticleHit {
  id: string
  law: string
  article_no: string
  rrf?: number
  dense_rank?: number | null
  sparse_rank?: number | null
}
export interface TlEvent {
  stage: string
  [k: string]: any
}
export interface CitationRow {
  law: string
  article_no: string
  quote?: string
  in_context: boolean
  quote_ratio: number | null
  band: string
  chunk_id: string | null
  turn?: number
}
export interface BadcaseBadge {
  badcase_id: string
  rules: string[]
  primary_stage: string
  severity: string
  status: string
  triggered_rules: { rule_id: string; threshold: unknown; observed: unknown; evidence: string }[]
}
export interface AnswerPayload {
  answer: string
  retrieved_ids: string[]
  intent?: string
  confidence?: number
  judge?: { mos: number; dimensions: Record<string, number>; reason?: string } | null
  demo?: boolean
  mock?: boolean
  latency_ms?: number
  turn_no?: number
  badcases?: BadcaseBadge[]
}
export interface Settings {
  models: { intent: string; generation: string; judge: string }
  retrieval: {
    topk: number; lane_fetch: number; rrf_k: number
    react_max_rounds: number; suff_th: number; fp_th: number; veto_enabled: boolean
  }
  judge_live: boolean
}
export interface Chunk {
  id: string; law: string; article_no: string; text: string
  chapter?: string; book?: string; clause?: string
  version?: string; effective_date?: string; status?: string; keywords?: string[]
}

const req = async (url: string, init?: RequestInit) => {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}
export const api = {
  settings: () => req('/api/settings') as Promise<Settings>,
  saveSettings: (s: Settings) =>
    req('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(s) }),
  keys: () => req('/api/settings/keys') as Promise<Record<string, { set: boolean; tail: string }>>,
  saveKeys: (patch: Record<string, string>) =>
    req('/api/settings/keys', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }),
  laws: (law: string, search: string, page: number, size = 20) =>
    req(`/api/laws?law=${encodeURIComponent(law)}&search=${encodeURIComponent(search)}&page=${page}&size=${size}`),
  law: (id: string) => req(`/api/laws/${encodeURIComponent(id)}`) as Promise<Chunk>,
  updateChunk: (id: string, patch: Partial<Chunk>) =>
    req(`/api/chunks/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }),
  createChunk: (c: Partial<Chunk>) =>
    req('/api/chunks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c) }),
  deleteChunk: (id: string) => req(`/api/chunks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  audit: () => req('/api/audit'),
  evals: () => req('/api/evals'),
  usage: () => req('/api/usage'),
  turns: (sid: string) => req(`/api/sessions/${encodeURIComponent(sid)}/turns`) as Promise<TurnRow[]>,
  badcases: (f: { stage?: string; severity?: string; source?: string; status?: string }) => {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][])
    return req(`/api/badcases?${q}`) as Promise<BadcaseRow[]>
  },
  badcaseStats: () => req('/api/badcases/stats') as Promise<BadcaseStats>,
  thumbDown: (sessionId: string, turnNo: number, note = '') =>
    req('/api/badcases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, turn_no: turnNo, note }) }),
  patchBadcase: (id: string, patch: Record<string, unknown>) =>
    req(`/api/badcases/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }),
  badcaseEvent: (id: string, body: Record<string, unknown>) =>
    req(`/api/badcases/${encodeURIComponent(id)}/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  verifyBadcase: (id: string) =>
    req(`/api/badcases/${encodeURIComponent(id)}/verify`, { method: 'POST' }),
}

export interface BadcaseRow {
  badcase_id: string
  session_id: string | null
  turn_id: number | null
  request_id: number | null
  source: string
  triggered_rules: { rule_id: string; threshold: unknown; observed: unknown; evidence: string }[]
  primary_stage: string
  secondary_stages: string[]
  severity: string
  scores: { dimensions?: Record<string, number>; mos?: number; item_id?: number; version?: string } | null
  status: string
  linked_case_id: string | null
  linked_issue_id: string | null
  created_at: number
  query_preview: string
}
export interface BadcaseStats {
  total: number
  by_stage: Record<string, number>
  by_rule: Record<string, number>
  by_severity: Record<string, number>
  by_status: Record<string, number>
  open_by_stage: Record<string, number>
  issue_drafts: { stage: string; open_n: number; draft: string }[]
}

export interface TurnRow {
  turn_no: number
  user_query: string
  intent_label: string | null
  retrieved_law_ids: { law: string; article_no: string; chunk_id: string }[]
  answer: string
  citations: CitationRow[]
  judge_scores: AnswerPayload['judge']
  status: string
  used_history_article_ids: { law: string; article_no: string; chunk_id: string }[]
}

export interface ChatHandlers {
  onState: (e: TlEvent) => void
  onSubtitle: (text: string) => void
  onAnswer: (a: AnswerPayload) => void
  onError: (message: string) => void
}
/** POST SSE：fetch 流式读取（EventSource 不支持 POST） */
export async function streamChat(query: string, demo: boolean, sessionId: string, h: ChatHandlers, signal?: AbortSignal) {
  const r = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, demo_mode: demo, session_id: sessionId }),
    signal,
  })
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const p of parts) {
      const ev = /^event: (.+)$/m.exec(p)?.[1]
      const dataStr = /^data: (.*)$/ms.exec(p)?.[1]
      if (!ev || !dataStr) continue
      const data = JSON.parse(dataStr)
      if (ev === 'state') h.onState(data)
      else if (ev === 'subtitle') h.onSubtitle(data.text)
      else if (ev === 'answer') h.onAnswer(data)
      else if (ev === 'error') h.onError(data.message)
    }
  }
}
