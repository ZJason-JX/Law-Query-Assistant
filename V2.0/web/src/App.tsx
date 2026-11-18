import { useState } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Radio } from 'antd'
import ChatPage from './pages/ChatPage'
import AdminPage from './pages/AdminPage'

function ChatIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 3h12v8H6l-4 3V3z" /></svg>
}
function AdminIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 4h12M2 8h12M2 12h7" /></svg>
}

export default function App() {
  const [demo, setDemo] = useState(false)
  const loc = useLocation()
  const onChat = loc.pathname.startsWith('/chat')
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">§</div>
          <div>
            <div className="brand-name">法律问答助手</div>
            <div className="brand-scope">2.0 · RAG + ReAct</div>
          </div>
        </div>
        <NavLink to="/chat" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <ChatIcon />对话
        </NavLink>
        <NavLink to="/admin" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <AdminIcon />管理后台
        </NavLink>
        <div className="sidebar-foot">
          本地工作区<br />6 部法律 · 1868 条<br />检索 v0.6-RRF · 生成 v1.2
        </div>
      </aside>
      <div className="main">
        <div className="topbar">
          <div className="topbar-title">{onChat ? '对话 / 链路观测' : '管理后台 / 配置与数据'}</div>
          {onChat && (
            <Radio.Group value={demo} onChange={e => setDemo(e.target.value)} size="small">
              <Radio.Button value={false}>真实问答</Radio.Button>
              <Radio.Button value={true}>id29 演示模式</Radio.Button>
            </Radio.Group>
          )}
        </div>
        <div className="sheet">
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage demo={demo} setDemo={setDemo} />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}
