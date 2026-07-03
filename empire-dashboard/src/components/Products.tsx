'use client'

import { useDashboard } from '@/lib/DashboardContext'
import type { Product } from '@/lib/types'

const COLUMNS: Array<{ label: string; statuses: string[] }> = [
  { label: 'Active', statuses: ['Building', 'Active'] },
  { label: 'Planning', statuses: ['Planning'] },
  { label: 'Backlog', statuses: ['Backlog', 'Done'] },
]

export function Products({ onProductClick }: { onProductClick: (id: string) => void }) {
  const { products, tasks, pct } = useDashboard()

  function col(p: Product) {
    if (p.status === 'Building' || p.status === 'Active') return 'Active'
    if (p.status === 'Planning') return 'Planning'
    return 'Backlog'
  }

  return (
    <>
      <div className="page-title">Products</div>
      <div className="kanban">
        {COLUMNS.map(c => {
          const items = products.filter(p => col(p) === c.label)
          return (
            <div key={c.label} className="k-col">
              <div className="k-col-head">
                {c.label}
                <span className="k-count">{items.length}</span>
              </div>
              {items.map(pr => {
                const pc = pct(pr.id)
                const open = tasks.filter(t => t.product_id === pr.id && !t.done).length
                return (
                  <div key={pr.id} className="k-card" onClick={() => onProductClick(pr.id)}>
                    <div className="k-card-name" style={{ color: pr.text_color }}>{pr.name}</div>
                    <div className="prog" style={{ margin: '6px 0 4px' }}>
                      <div className="prog-fill" style={{ width: `${pc}%`, background: pr.color }} />
                    </div>
                    <div className="k-card-sub">{pc}% complete · {open} task{open !== 1 ? 's' : ''} open</div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </>
  )
}
