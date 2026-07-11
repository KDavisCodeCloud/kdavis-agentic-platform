'use client'

import { useState } from 'react'
import { useDashboard } from '@/lib/DashboardContext'
import type { Task, TaskPriority, ProductStatus } from '@/lib/types'

const PRI_STYLE: Record<TaskPriority, string> = {
  high: 'background:#FCEBEB;color:#A32D2D',
  mid:  'background:#FAEEDA;color:#633806',
  low:  'background:#f2f1ee;color:#9a9a94',
}
const PRI_LABEL: Record<TaskPriority, string> = { high: 'High', mid: 'Med', low: 'Low' }
const ALL_STATUSES: ProductStatus[] = ['Building', 'Planning', 'Active', 'Backlog', 'Done']

function fmtDate(ts: string) {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
function fmtFull(ts: string) {
  return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function ProductDetail({ productId, onBack }: { productId: string; onBack: () => void }) {
  const { products, tasks, logs, pct, addTask, toggleTask, deleteTask, addLog, deleteLog, updateProduct } = useDashboard()
  const pr = products.find(p => p.id === productId)

  const [text, setText] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('mid')
  const [saving, setSaving] = useState(false)
  const [editPhase, setEditPhase] = useState(false)
  const [phaseText, setPhaseText] = useState(pr?.phase_note ?? '')
  const [editStatus, setEditStatus] = useState(false)
  const [logText, setLogText] = useState('')
  const [logSaving, setLogSaving] = useState(false)

  if (!pr) return null

  const prodTasks = tasks.filter(t => t.product_id === productId)
  const prodLogs = logs.filter(l => l.product_id === productId)
  const open = prodTasks.filter(t => !t.done)
  const done = prodTasks.filter(t => t.done)
  const pc = pct(productId)

  async function handleAddTask() {
    const t = text.trim()
    if (!t) return
    setSaving(true)
    await addTask(productId, t, priority)
    setText('')
    setSaving(false)
  }

  async function savePhase() {
    await updateProduct(productId, { phase_note: phaseText })
    setEditPhase(false)
  }

  async function saveStatus(status: ProductStatus) {
    await updateProduct(productId, { status })
    setEditStatus(false)
  }

  async function saveProgress(val: number) {
    await updateProduct(productId, { base_progress: val })
  }

  async function handleAddLog() {
    const t = logText.trim()
    if (!t) return
    setLogSaving(true)
    await addLog(productId, t)
    setLogText('')
    setLogSaving(false)
  }

  function TaskRow({ task }: { task: Task }) {
    return (
      <div className="task-row">
        <div
          className={`cb${task.done ? ' done' : ''}`}
          role="checkbox"
          aria-checked={task.done}
          tabIndex={0}
          onClick={() => toggleTask(task.id, !task.done)}
          onKeyDown={e => e.key === 'Enter' && toggleTask(task.id, !task.done)}
        />
        <div className="task-body">
          <div className="task-tags">
            <span className="tag" style={parseSty(PRI_STYLE[task.priority])}>{PRI_LABEL[task.priority]}</span>
            <span style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{fmtDate(task.created_at)}</span>
          </div>
          <div className={`task-text${task.done ? ' done' : ''}`}>{task.text}</div>
          {task.done && task.done_at && <div className="task-meta">Completed {fmtFull(task.done_at)}</div>}
        </div>
        <button className="del-btn" onClick={() => deleteTask(task.id)} aria-label="Delete">×</button>
      </div>
    )
  }

  return (
    <>
      <button className="back-btn" onClick={onBack}>← All products</button>

      <div className="detail-head">
        <span className="detail-dot" style={{ background: pr.color }} />
        <span className="detail-name" style={{ color: pr.text_color }}>{pr.name}</span>
        <span
          className="status-pill"
          style={{ background: `${pr.bg_color}`, color: pr.text_color, cursor: 'pointer' }}
          onClick={() => setEditStatus(v => !v)}
          title="Click to change status"
        >
          {pr.status}
        </span>
      </div>

      {editStatus && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {ALL_STATUSES.map(s => (
            <button
              key={s}
              className="f-btn"
              style={s === pr.status ? { background: pr.color, color: '#fff', borderColor: 'transparent' } : {}}
              onClick={() => saveStatus(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {editPhase ? (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
          <input
            type="text"
            value={phaseText}
            onChange={e => setPhaseText(e.target.value)}
            style={{ flex: 1 }}
            onKeyDown={e => { if (e.key === 'Enter') savePhase(); if (e.key === 'Escape') setEditPhase(false) }}
            autoFocus
          />
          <button className="btn" onClick={savePhase}>Save</button>
          <button className="btn-ghost" onClick={() => setEditPhase(false)}>Cancel</button>
        </div>
      ) : (
        <div className="phase-note" onClick={() => { setPhaseText(pr.phase_note); setEditPhase(true) }} style={{ cursor: 'pointer' }} title="Click to edit">
          {pr.phase_note || 'Click to add a phase note…'}
        </div>
      )}

      <div className="stat-grid-3">
        <div className="stat-card">
          <div className="stat-num" style={{ color: pr.color }}>{pc}%</div>
          <div className="stat-lbl">Progress</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{open.length}</div>
          <div className="stat-lbl">Open tasks</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{done.length}</div>
          <div className="stat-lbl">Completed</div>
        </div>
      </div>

      <div className="prog" style={{ height: 8 }}>
        <div className="prog-fill" style={{ width: `${pc}%`, background: pr.color }} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0 16px' }}>
        <span style={{ fontSize: 11, color: 'var(--text3)' }}>Base progress</span>
        <input
          type="range"
          min={0}
          max={100}
          defaultValue={pr.base_progress}
          style={{ flex: 1 }}
          onMouseUp={e => saveProgress(Number((e.target as HTMLInputElement).value))}
          onTouchEnd={e => saveProgress(Number((e.target as HTMLInputElement).value))}
        />
        <span style={{ fontSize: 11, color: 'var(--text3)', minWidth: 28 }}>{pr.base_progress}%</span>
      </div>

      <div className="section-lbl" style={{ marginTop: 0 }}>Add task</div>
      <div className="task-area">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="What needs to get done..."
            style={{ flex: 1, minWidth: 160 }}
            onKeyDown={e => { if (e.key === 'Enter') handleAddTask() }}
          />
          <select value={priority} onChange={e => setPriority(e.target.value as TaskPriority)} style={{ height: 36 }}>
            <option value="high">High</option>
            <option value="mid">Med</option>
            <option value="low">Low</option>
          </select>
          <button className="btn" onClick={handleAddTask} disabled={saving}>+ Add</button>
        </div>
      </div>

      <div className="section-lbl">Open tasks</div>
      {open.length ? (
        <div className="task-area">{open.map(t => <TaskRow key={t.id} task={t} />)}</div>
      ) : (
        <div className="empty-state">No open tasks for this product.</div>
      )}

      <div className="section-lbl" style={{ marginTop: 18 }}>Completed</div>
      {done.length ? (
        <div className="task-area">{done.map(t => <TaskRow key={t.id} task={t} />)}</div>
      ) : (
        <div className="empty-state">Nothing completed yet.</div>
      )}

      <div className="section-lbl" style={{ marginTop: 18 }}>Session notes</div>
      <div className="task-area">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <textarea
            value={logText}
            onChange={e => setLogText(e.target.value)}
            placeholder="What got done? What's blocked? What's next?"
            rows={2}
            style={{ flex: 1, minWidth: 200 }}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleAddLog() }}
          />
          <button className="btn" onClick={handleAddLog} disabled={logSaving}>Log it</button>
        </div>
      </div>
      {prodLogs.length ? (
        prodLogs.map(l => (
          <div key={l.id} className="log-card">
            <div className="log-meta">
              <span>{fmtFull(l.created_at)}</span>
              <button className="log-del" onClick={() => deleteLog(l.id)}>×</button>
            </div>
            <div className="log-text">{l.content}</div>
          </div>
        ))
      ) : (
        <div className="empty-state">No session notes for this product yet.</div>
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
