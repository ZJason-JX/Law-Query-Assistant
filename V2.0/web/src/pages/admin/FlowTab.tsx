import { FlowDiagram } from '../../components/FlowDiagram'

const CHIP = {
  judge: '#a78bfa', ret: '#8b5cf6', gen: '#c4b5fd', audit: '#a855f7', side: '#e879f9',
}

export default function FlowTab() {
  return (
    <div>
      <div className="page-sub" style={{ marginBottom: 12 }}>
        一条法律问题从提问到回答的完整过程。S0–S5 是链路的五个步骤
        （与右侧时间线、坏例队列里的「环节」一一对应），虚线是分支与旁路。
      </div>
      <div style={{ borderRadius: 16, overflow: 'hidden', background: '#0d0a1f', maxWidth: 920 }}>
        <FlowDiagram />
      </div>
      <div className="msg-meta" style={{ marginTop: 14 }}>
        <span className="tag" style={{ borderColor: CHIP.judge, color: CHIP.judge }}>亮紫 = 做判断（S0 / S2）</span>
        <span className="tag" style={{ borderColor: CHIP.ret, color: CHIP.ret }}>紫 = 找法条（S1 / S3）</span>
        <span className="tag" style={{ borderColor: CHIP.gen, color: CHIP.gen }}>浅紫 = 写回答（S4）</span>
        <span className="tag" style={{ borderColor: CHIP.audit, color: CHIP.audit }}>品紫 = 核对引用（S5）</span>
        <span className="tag" style={{ borderColor: CHIP.side, color: CHIP.side }}>品红虚线 = 拒答与坏例旁路</span>
      </div>
    </div>
  )
}
