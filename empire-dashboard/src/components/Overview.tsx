'use client'

import { useDashboard } from '@/lib/DashboardContext'

function isToday(ts: string) {
  const d = new Date(ts)
  const n = new Date()
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate()
}

const STATUS_STYLE: Record<string, string> = {
  Building: 'background:#E6F1FB;color:#0C447C',
  Planning:  'background:#FAEEDA;color:#633806',
  Active:    'background:#E1F5EE;color:#085041',
  Backlog:   'background:#f2f1ee;color:#9a9a94',
  Done:      'background:#E1F5EE;color:#085041',
}

export function Overview({ onProductClick }: { onProductClick: (id: string) => void }) {
  const { tasks, logs, products, pct } = useDashboard()

  const done = tasks.filter(t => t.done).length
  const open = tasks.filter(t => !t.done).length
  const today = tasks.filter(t => t.done && t.done_at && isToday(t.done_at)).length

  return (
    <>
      <div className="page-title">Command center</div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-num">{open}</div>
          <div className="stat-lbl">Open tasks</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{done}</div>
          <div className="stat-lbl">Completed</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{today}</div>
          <div className="stat-lbl">Done today</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{logs.length}</div>
          <div className="stat-lbl">Session logs</div>
        </div>
      </div>

      <div className="section-lbl">All products</div>

      {products.map(pr => {
        const pc = pct(pr.id)
        const openCount = tasks.filter(t => t.product_id === pr.id && !t.done).length
        return (
          <div key={pr.id} className="prod-card" onClick={() => onProductClick(pr.id)}>
            <div className="prod-card-top">
              <span className="sdot" style={{ background: pr.color }} />
              <span className="prod-card-name">{pr.name}</span>
              <span className="status-pill" style={{ ...(STATUS_STYLE[pr.status] ? undefined : {}), ...(parseSty(STATUS_STYLE[pr.status])) }}>{pr.status}</span>
            </div>
            <div className="prog">
              <div className="prog-fill" style={{ width: `${pc}%`, background: pr.color }} />
            </div>
            <div className="prog-meta">
              <span>{pr.phase_note}</span>
              <span>{pc}% · {openCount} open</span>
            </div>
          </div>
        )
      })}
    </>
  )
}

function parseSty(s: string): React.CSSProperties {
  if (!s) return {}
  return Object.fromEntries(
    s.split(';').filter(Boolean).map(p => {
      const [k, v] = p.split(':').map(x => x.trim())
      const camel = k.replace(/-([a-z])/g, (_,c) => c.toUpperCase())
      return [camel, v]
    })
  ) as React.CSSProperties
}
