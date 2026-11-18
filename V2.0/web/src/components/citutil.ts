// 法条名/条号规范化：与后端 verify_citations 的口径对齐（简写 chip 用）
export const LAW_ABBR: Record<string, string> = {
  '中华人民共和国劳动合同法': '劳合',
  '劳动合同法': '劳合',
  '中华人民共和国劳动法': '劳动',
  '劳动法': '劳动',
  '中华人民共和国民法典': '民',
  '民法典': '民',
  '中华人民共和国公司法': '公司',
  '公司法': '公司',
  '中华人民共和国反不正当竞争法': '反法',
  '反不正当竞争法': '反法',
  '中华人民共和国消费者权益保护法': '消保',
  '消费者权益保护法': '消保',
}
export const normLaw = (s: string) => s.replace(/[《》]/g, '').replace('中华人民共和国', '').trim()
export const abbr = (law: string) => LAW_ABBR[law] ?? LAW_ABBR[normLaw(law)] ?? normLaw(law).slice(0, 2)

const CN: Record<string, number> = { 零: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10, 百: 100, 千: 1000 }
export function cn2num(s: string): number {
  if (/^\d+$/.test(s)) return parseInt(s, 10)
  let sec = 0, num = 0
  for (const ch of s) {
    const v = CN[ch]
    if (v == null) return -1
    if (v >= 10) { sec += (num || 1) * v; num = 0 } else num = v
  }
  return sec + num
}
export const normArt = (s: string) => {
  const m = /第(.+?)条/.exec(s)
  const inner = m ? m[1] : s.replace(/[第条款项\s]/g, '')
  const n = cn2num(inner)
  return n >= 0 ? String(n) : inner
}
export const citKey = (law: string, art: string) => `${normLaw(law)}#${normArt(art)}`

export interface ParsedCitation { law: string; article_no: string; quote?: string }
/** 从回答文本拆出末尾 JSON 引用块；正文保留免责声明 */
export function splitAnswer(text: string): { body: string; citations: ParsedCitation[] } {
  const re = /\[\s*\{[^{}]*"law"[^{}]*\}\s*(?:,\s*\{[^{}]*\}\s*)*\]/
  const m = re.exec(text)
  if (!m) return { body: text, citations: [] }
  try {
    const citations = JSON.parse(m[0]) as ParsedCitation[]
    return { body: (text.slice(0, m.index) + text.slice(m.index + m[0].length)).trim(), citations }
  } catch {
    return { body: text, citations: [] }
  }
}
