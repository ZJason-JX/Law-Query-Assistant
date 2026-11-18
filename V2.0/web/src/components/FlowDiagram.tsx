// 全链路架构图：S0–S5 主链路 + 拒答分支 + 门控回环 + 坏例旁路
// 深紫黑科技风；主链路居中竖排，回环走左侧车道，拒答与注解走右列，箭头不交叉
const C = {
  txt: '#f0e9ff', mut: '#b3a8d9', dim: '#8f83b8',
  judge: '#a78bfa', ret: '#8b5cf6', gen: '#c4b5fd', audit: '#a855f7',
  io: '#6d28d9', side: '#e879f9', line: '#a78bfa',
}

function Box({ x, y, w, h, title, lines, stroke, glow }: {
  x: number; y: number; w: number; h: number
  title: string; lines: string[]; stroke: string; glow?: boolean
}) {
  return (
    <g style={glow ? { filter: `drop-shadow(0 0 8px ${stroke}44)` } : undefined}>
      <rect x={x} y={y} width={w} height={h} rx={10}
            fill={`${stroke}14`} stroke={stroke} strokeWidth={1.4} />
      <rect x={x + 10} y={y + 10} width={4} height={16} rx={2} fill={stroke} />
      <text x={x + 24} y={y + 23} fontSize={13.5} fontWeight={700} fill={C.txt}>{title}</text>
      {lines.map((l, i) => (
        <text key={i} x={x + 14} y={y + 42 + i * 16} fontSize={11.5} fill={C.mut}>{l}</text>
      ))}
    </g>
  )
}

function Arrow({ d, dashed, label, lx, ly, nohead }: {
  d: string; dashed?: boolean; label?: string; lx?: number; ly?: number; nohead?: boolean
}) {
  return (
    <g>
      <path d={d} fill="none" stroke={dashed ? C.side : C.line} strokeWidth={1.6}
            strokeDasharray={dashed ? '5 4' : undefined}
            markerEnd={nohead ? undefined : (dashed ? 'url(#ahSide)' : 'url(#ah)')} />
      {label && <text x={lx} y={ly} fontSize={11} fill={C.dim}>{label}</text>}
    </g>
  )
}

export function FlowDiagram() {
  const X0 = 90, W = 330, XR = 560, WR = 320, CX = X0 + W / 2
  return (
    <svg viewBox="0 0 900 830" style={{ width: '100%', height: 'auto', display: 'block' }} role="img">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0d0a1f" />
          <stop offset="100%" stopColor="#171029" />
        </linearGradient>
        <marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
          <path d="M0,0 L9,4.5 L0,9 Z" fill={C.line} />
        </marker>
        <marker id="ahSide" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
          <path d="M0,0 L9,4.5 L0,9 Z" fill={C.side} />
        </marker>
      </defs>
      <rect x={0} y={0} width={900} height={830} rx={16} fill="url(#bg)" />

      {/* 输入 */}
      <Box x={X0} y={20} w={W} h={48} title="用户提问" stroke={C.io}
           lines={['日常语言描述问题，可在同一会话追问']} />
      <Arrow d={`M${CX} 68 V100`} />

      {/* S0 */}
      <Box x={X0} y={100} w={W} h={64} title="S0 先看懂你在问什么" stroke={C.judge} glow
           lines={['判断问题类型（找法条 / 构成要件 / 冲突 / 概念）', '以及问题的前提是否有误']} />
      <Arrow d={`M${CX} 164 V198`} />
      <Arrow d={`M${X0 + W} 132 H${XR}`} dashed label="与法律无关" lx={X0 + W + 14} ly={124} />
      <Box x={XR} y={100} w={WR} h={64} title="直接拒答" stroke={C.side}
           lines={['问题与法律无关或无法判断时', '给出礼貌说明，流程到此结束']} />

      {/* S1 */}
      <Box x={X0} y={198} w={W} h={76} title="S1 第一遍找法条" stroke={C.ret} glow
           lines={['把问题改写成 3 种问法一起查', '语义相似 + 关键词匹配两路并查', '合并排序，取最相关的前 10 条']} />
      <Arrow d={`M${CX} 274 V308`} />
      <Arrow d={`M${X0 + W} 236 H${XR}`} dashed nohead />
      <Box x={XR} y={186} w={WR} h={116} title="向量库：怎么建 · 怎么搜 · 为什么" stroke={C.ret}
           lines={['建库：1868 条法条按条切分，一条 = 一个检索单元',
                    '每条存两种指纹：语义向量（BGE-M3）+ 关键词权重',
                    '搜索：3 种问法 × 两路并查 → 合并排序取前 10',
                    '为什么两路：口语「裁员」≠ 法条「解除劳动合同」，',
                    '单靠一种匹配会漏；二次精排实测更差，已弃用']} />

      {/* S2 */}
      <Box x={X0} y={308} w={W} h={64} title="S2 证据够不够？" stroke={C.judge} glow
           lines={['判断模型通读找到的法条', '够 → 写答案；不够 → 补查一轮']} />
      <Arrow d={`M${CX} 372 V406`} label="不够" lx={CX + 12} ly={394} />
      <Arrow d={`M${X0 + W} 340 H500 V562 H${X0 + W}`} label="够了，直接写答案" lx={X0 + W + 12} ly={332} />
      <Box x={XR} y={308} w={WR} h={64} title="判断模型（只判断不写作）" stroke={C.judge}
           lines={['负责 S0 分类与 S2「证据够不够」', '每次约 0.1–0.5 秒，带可信度']} />

      {/* S3 */}
      <Box x={X0} y={406} w={W} h={76} title="S3 针对缺口再补查（最多 5 轮）" stroke={C.ret} glow
           lines={['按缺的内容生成新问法', '纠正错误前提 / 补没查到的法律 / 补角度', '查到后回到 S2 重新判断']} />
      <Arrow d={`M${X0} 444 H40 V340 H${X0}`} dashed label="回到 S2" lx={42} ly={330} />
      <Arrow d={`M${CX} 482 V530`} label="够了 / 轮次用满" lx={CX + 12} ly={510} />
      <Box x={XR} y={406} w={WR} h={76} title="目前的短板（已记录）" stroke={C.io}
           lines={['门控偏严：约九成问题都进补查轮', '多步推理、高置信误判仍在改进', '在「坏例队列」持续跟踪']} />

      {/* S4 */}
      <Box x={X0} y={530} w={W} h={64} title="S4 组织成回答" stroke={C.gen} glow
           lines={['按问题类型选对应的回答模板', '前提有误的问题先纠正再作答']} />
      <Arrow d={`M${CX} 594 V628`} />
      <Box x={XR} y={530} w={WR} h={64} title="写作模型" stroke={C.gen}
           lines={['豆包 / DeepSeek 可切换', '每类问题一套独立回答模板']} />

      {/* S5 */}
      <Box x={X0} y={628} w={W} h={64} title="S5 逐条核对引用（程序检查）" stroke={C.audit} glow
           lines={['答案引的每条法条，核对是否真在', '检索结果里，并标注是否原文引用']} />
      <Arrow d={`M${CX} 692 V726`} />
      <Arrow d={`M${X0 + W} 660 H${XR}`} dashed label="S5 后旁路登记" lx={X0 + W + 12} ly={652} />
      <Box x={XR} y={628} w={WR} h={76} title="坏例自动登记（旁路）" stroke={C.side}
           lines={['引用越界 / 判断没把握 / 前提没纠正', '补查用满 / 回答太慢 → 进坏例队列', '修复后复跑验证，全部通过才关闭']} />

      {/* 输出 */}
      <Box x={X0} y={726} w={W} h={64} title="输出回答" stroke={C.io}
           lines={['引用法条 + 通俗解释 + 行为建议', '附引用清单，可点开看法条原文']} />
      <Box x={XR} y={726} w={WR} h={64} title="数据落库" stroke={C.io}
           lines={['问答与引用核对全部入库', '追问时最多带入最近 3 轮上下文']} />
    </svg>
  )
}
