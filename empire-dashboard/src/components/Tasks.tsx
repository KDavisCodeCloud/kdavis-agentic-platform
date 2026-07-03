'use client'

import { useState } from 'react'
import { useDashboard } from '@/lib/DashboardContext'
import type { Task, TaskPriority } from '@/lib/types'

const PRI_STYLE: Record<TaskPriority, string> = {
  high: 'background:#FCEBEB;color:#A32D2D',
  mid:  'background:#FAEEDA;color:#633806',
  low:  'background:#f2f1ee;color:#9a9a94',
}
const PRI_LABEL: Record<TaskPriority, string> = { high: 'High', mid: 'Med', low: 'Low' }

function fmtDate(ts: string) {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
function fmtDone(ts: string) {
  return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function TaskRow({ task, products, onToggle, onDelete }: {
  task: Task
  products: ReturnType<typeof useDashboard>['products']
  onToggle: (id: number, done: boolean) => void
  onDelete: (id: number) => void
}) {
  const pr = products.find(p => p.id === task.product_id)
  return (
    <div className="task-row">
      <div
        className={`cb${task.done ? ' done' : ''}`}
        role="checkbox"
        aria-checked={task.done}
        tabIndex={0}
        onClick={() => onToggle(task.id, !task.done)}
        onKeyDown={e => e.key === 'Enter' && onToggle(task.id, !task.done)}
      />
      <div className="task-body">
        <div className="task-tags">
          {pr && <span className="tag" style={{ background: pr.bg_color, color: pr.text_color }}>{pr.name}</span>}
          <span className="tag" style={{ ...(PRI_STYLE[task.priority] ? parseSty(PRI_STYLE[task.priority]) : {}) }}>
            {PRI_LABEL[task.priority]}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{fmtDate(task.created_at)}</span>
        </div>
        <div className={`task-text${task.done ? ' done' : ''}`}>{task.text}</div>
        {task.done && task.done_at && (
          <div className="task-meta">Completed {fmtDone(task.done_at)}</div>
        )}
      </div>
      <button className="del-btn" onClick={() => onDelete(task.id)} aria-label="Delete task">×</button>
    </div>
  )
}

export function Tasks() {
  const { tasks, products, addTask, toggleTask, deleteTask } = useDashboard()
  const [filter, setFilter] = useState('All')
  const [text, setText] = useState('')
  const [prodId, setProdId] = useState(products[0]?.id ?? '')
  const [priority, setPriority] = useState<TaskPriority>('mid')
  const [saving, setSaving] = useState(false)

  async function handleAdd() {
    const t = text.trim()
    if (!t || !prodId) return
    setSaving(true)
    await addTask(prodId, t, priority)
    setText('')
    setSaving(false)
  }

  const visible = filter === 'All' ? tasks : tasks.filter(t => t.product_id === filter)
  const active = visible.filter(t => !t.done)
  const done = visible.filter(t => t.done)

  return (
    <>
      <div className="page-title">Tasks</div>

      <div className="task-area">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Add a task..."
            style={{ flex: 1, minWidth: 160 }}
            onKeyDown={e => { if (e.key === 'Enter') handleAdd() }}
          />
          <select value={prodId} onChange={e => setProdId(e.target.value)} style={{ height: 36 }}>
            {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select value={priority} onChange={e => setPriority(e.target.value as TaskPriority)} style={{ height: 36 }}>
            <option value="high">High</option>
            <option value="mid">Medium</option>
            <option value="low">Low</option>
          </select>
          <button className="btn" onClick={handleAdd} disabled={saving}>+ Add</button>
        </div>
      </div>

      <div className="filters">
        {['All', ...products.map(p => p.id)].map(f => {
          const pr = products.find(p => p.id === f)
          const on = filter === f
          const label = f === 'All' ? 'All' : (pr?.name ?? f)
          const style = on && pr ? { background: pr.color, color: '#fff', borderColor: 'transparent' } : {}
          const allOn = on && f === 'All'
          return (
            <button
              key={f}
              className={`f-btn${on ? ' on' : ''}`}
              style={allOn ? { background: 'var(--text)', color: 'var(--bg)', borderColor: 'transparent' } : style}
              onClick={() => setFilter(f)}
            >
              {label}
            </button>
          )
        })}
      </div>

      <div className="section-lbl">Open</div>
      {active.length ? (
        <div className="task-area">
          {active.map(t => <TaskRow key={t.id} task={t} products={products} onToggle={toggleTask} onDelete={deleteTask} />)}
        </div>
      ) : (
        <div className="empty-state">No open tasks{filter !== 'All' ? ' for this product' : ''}.</div>
      )}

      <div className="section-lbl" style={{ marginTop: 20 }}>Completed</div>
      {done.length ? (
        <div className="task-area">
          {done.map(t => <TaskRow key={t.id} task={t} products={products} onToggle={toggleTask} onDelete={deleteTask} />)}
        </div>
      ) : (
        <div className="empty-state">Nothing completed yet.</div>
      )}
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
