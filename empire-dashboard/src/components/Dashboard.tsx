'use client'

import { useState } from 'react'
import { supabase } from '@/lib/supabase'
import { useDashboard } from '@/lib/DashboardContext'
import { Overview } from './Overview'
import { Tasks } from './Tasks'
import { Products } from './Products'
import { Sessions } from './Sessions'
import { ProductDetail } from './ProductDetail'
import type { TabId } from '@/lib/types'

export function Dashboard() {
  const { products, loading } = useDashboard()
  const [tab, setTab] = useState<TabId>('overview')
  const [productId, setProductId] = useState<string | null>(null)

  function goProduct(id: string) {
    setProductId(id)
  }

  function goBack() {
    setProductId(null)
    setTab('products')
  }

  function navTab(t: TabId) {
    setProductId(null)
    setTab(t)
  }

  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })

  if (loading) return <div className="loading-screen">Loading data…</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Topbar */}
      <div className="topbar">
        <div className="topbar-logo">Decoded Empire</div>
        <nav className="topbar-nav">
          {(['overview', 'tasks', 'products', 'sessions'] as TabId[]).map(t => (
            <button
              key={t}
              className={`tnav${tab === t && !productId ? ' active' : ''}`}
              onClick={() => navTab(t)}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
        <div className="topbar-right">{today}</div>
      </div>

      {/* Body */}
      <div className="layout">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-label">Navigate</div>
          {(['overview', 'tasks', 'products', 'sessions'] as TabId[]).map(t => (
            <button
              key={t}
              className={`sitem${tab === t && !productId ? ' active' : ''}`}
              onClick={() => navTab(t)}
            >
              ▪ {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}

          <div className="sdivider" />
          <div className="sidebar-label">Products</div>
          {products.map(p => (
            <button
              key={p.id}
              className={`sitem${productId === p.id ? ' active' : ''}`}
              onClick={() => goProduct(p.id)}
            >
              <span className="sdot" style={{ background: p.color }} />
              {p.name}
            </button>
          ))}

          <div className="sdivider" />
          <button className="btn-ghost" style={{ margin: '4px 4px 0', fontSize: 11 }} onClick={signOut}>
            Sign out
          </button>
        </aside>

        {/* Main content */}
        <main className="main">
          {productId ? (
            <ProductDetail productId={productId} onBack={goBack} />
          ) : tab === 'overview' ? (
            <Overview onProductClick={goProduct} />
          ) : tab === 'tasks' ? (
            <Tasks />
          ) : tab === 'products' ? (
            <Products onProductClick={goProduct} />
          ) : (
            <Sessions />
          )}
        </main>
      </div>
    </div>
  )
}

async function signOut() {
  await supabase.auth.signOut()
}
