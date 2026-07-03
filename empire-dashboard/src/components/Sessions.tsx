'use client'

import { useState } from 'react'
import { useDashboard } from '@/lib/DashboardContext'

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function Sessions() {
  const { logs, products, addLog, deleteLog } = useDashboard()
  const [selectedProd, setSelectedProd] = useState(products[0]?.id ?? '')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleAdd() {
    const t = text.trim()
    if (!t || !selectedProd) return
    setSaving(true)
    await addLog(selectedProd, t)
    setText('')
    setSaving(false)
  }

  function prodById(id: string) {
    return products.find(p => p.id === id)
  }

  return (
    <>
      <div className="page-title">Session log</div>

      <div className="task-area">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <select
            value={selectedProd}
            onChange={e => setSelectedProd(e.target.value)}
            style={{ height: 36 }}
          >
            {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="What got done? What's blocked? What's next?"
            rows={2}
            style={{ flex: 1, minWidth: 200 }}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleAdd() }}
          />
          <button className="btn" onClick={handleAdd} disabled={saving}>Log it</button>
        </div>
      </div>

      <div className="section-lbl">History</div>

      {logs.length === 0 ? (
        <div className="empty-state">No session logs yet. Log your first build session above.</div>
      ) : (
        logs.map(l => {
          const pr = prodById(l.product_id)
          return (
            <div key={l.id} className="log-card">
              <div className="log-meta">
                <span>{fmtDate(l.created_at)}</span>
                {pr && (
                  <span className="tag" style={{ background: pr.bg_color, color: pr.text_color }}>
                    {pr.name}
                  </span>
                )}
                <button className="log-del" onClick={() => deleteLog(l.id)}>×</button>
              </div>
              <div className="log-text">{l.content}</div>
            </div>
          )
        })
      )}
    </>
  )
}
