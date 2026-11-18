// 开发用交互截图：演示模式重放 + 管理页四个 Tab。复用 skill 的 CDP 客户端，无新依赖。
// 运行：node web/shot.mjs   （需后端 :8000 与前端 dev :5173 都在运行）
import { mkdirSync } from 'node:fs'
import { Browser, sleep } from '../../.claude/skills/design-taste-frontend/scripts/lib/cdp.mjs'

const OUT = '.taste-skill/shots'
mkdirSync(OUT, { recursive: true })
const b = await Browser.launch({ width: 1440, height: 900 })
const p = await b.newPage({ width: 1440, height: 900 })

await p.goto('http://localhost:5173/chat')
await sleep(1200)
// 切到演示模式并开始五幕重放
await p.eval(() => {
  const labels = [...document.querySelectorAll('.ant-radio-button-wrapper')]
  labels.find(x => x.textContent.includes('id29'))?.click()
})
await sleep(400)
await p.eval(() => {
  const btns = [...document.querySelectorAll('button')]
  btns.find(x => x.textContent.includes('开始演示') || x.textContent.includes('重放五幕'))?.click()
})
await sleep(6000)
await p.screenshot({ path: `${OUT}/demo-mid.jpg` })
await sleep(14000)
await p.screenshot({ path: `${OUT}/demo-final.jpg` })

await p.goto('http://localhost:5173/admin')
await sleep(1500)
await p.screenshot({ path: `${OUT}/admin-settings.jpg` })
for (const [tab, name] of [['知识库管理', 'laws'], ['评测看板', 'evals'], ['用量统计', 'usage']]) {
  await p.eval((t) => {
    const tabs = [...document.querySelectorAll('.ant-tabs-tab')]
    tabs.find(x => x.textContent.includes(t))?.click()
  }, tab)
  await sleep(1500)
  await p.screenshot({ path: `${OUT}/admin-${name}.jpg` })
}
await b.close()
console.log('shots saved to', OUT)
