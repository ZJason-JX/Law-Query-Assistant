import { Tabs } from 'antd'
import SettingsTab from './admin/SettingsTab'
import LawsTab from './admin/LawsTab'
import EvalsTab from './admin/EvalsTab'
import UsageTab from './admin/UsageTab'
import BadcaseTab from './admin/BadcaseTab'
import FlowTab from './admin/FlowTab'

export default function AdminPage() {
  return (
    <div className="sheet-pad">
      <div className="page-head">
        <div>
          <h1>管理后台</h1>
          <div className="page-sub">配置、知识库与审计、评测结果、真实请求用量。改动只作用于包装层，不触碰冻结的检索与生成逻辑。</div>
        </div>
      </div>
      <Tabs
        items={[
          { key: 'flow', label: '链路架构', children: <FlowTab /> },
          { key: 'settings', label: '设置', children: <SettingsTab /> },
          { key: 'laws', label: '知识库管理', children: <LawsTab /> },
          { key: 'evals', label: '评测看板', children: <EvalsTab /> },
          { key: 'usage', label: '用量统计', children: <UsageTab /> },
          { key: 'badcases', label: 'Badcase 队列', children: <BadcaseTab /> },
        ]}
      />
    </div>
  )
}
