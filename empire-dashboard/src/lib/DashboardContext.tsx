'use client'

import {
  createContext, useContext, useState, useEffect, useCallback, type ReactNode,
} from 'react'
import { supabase } from './supabase'
import type { Task, SessionLog, Product, TaskPriority } from './types'

interface DashboardContextType {
  tasks: Task[]
  logs: SessionLog[]
  products: Product[]
  loading: boolean
  pct: (productId: string) => number
  addTask: (productId: string, text: string, priority: TaskPriority) => Promise<void>
  toggleTask: (id: number, done: boolean) => Promise<void>
  deleteTask: (id: number) => Promise<void>
  addLog: (productId: string, content: string) => Promise<void>
  deleteLog: (id: number) => Promise<void>
  updateProduct: (id: string, updates: Partial<Pick<Product, 'status' | 'phase_note' | 'base_progress'>>) => Promise<void>
}

const DashboardCtx = createContext<DashboardContextType | null>(null)

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [logs, setLogs] = useState<SessionLog[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  const fetchAll = useCallback(async () => {
    const [{ data: p }, { data: t }, { data: l }] = await Promise.all([
      supabase.from('products').select('*').order('sort_order'),
      supabase.from('tasks').select('*').order('created_at', { ascending: false }),
      supabase.from('session_logs').select('*').order('created_at', { ascending: false }).limit(200),
    ])
    if (p) setProducts(p)
    if (t) setTasks(t)
    if (l) setLogs(l)
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchAll()

    const taskCh = supabase
      .channel('realtime-tasks')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'tasks' },
        (e) => setTasks(prev => [e.new as Task, ...prev]))
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'tasks' },
        (e) => setTasks(prev => prev.map(t => t.id === (e.new as Task).id ? e.new as Task : t)))
      .on('postgres_changes', { event: 'DELETE', schema: 'public', table: 'tasks' },
        (e) => setTasks(prev => prev.filter(t => t.id !== (e.old as Task).id)))
      .subscribe()

    const logCh = supabase
      .channel('realtime-logs')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'session_logs' },
        (e) => setLogs(prev => [e.new as SessionLog, ...prev]))
      .on('postgres_changes', { event: 'DELETE', schema: 'public', table: 'session_logs' },
        (e) => setLogs(prev => prev.filter(l => l.id !== (e.old as SessionLog).id)))
      .subscribe()

    const prodCh = supabase
      .channel('realtime-products')
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'products' },
        (e) => setProducts(prev => prev.map(p => p.id === (e.new as Product).id ? e.new as Product : p)))
      .subscribe()

    return () => {
      supabase.removeChannel(taskCh)
      supabase.removeChannel(logCh)
      supabase.removeChannel(prodCh)
    }
  }, [fetchAll])

  const pct = useCallback((productId: string) => {
    const prod = products.find(p => p.id === productId)
    if (!prod) return 0
    const done = tasks.filter(t => t.product_id === productId && t.done).length
    return Math.min(100, prod.base_progress + Math.round(done * 2))
  }, [products, tasks])

  const addTask = async (productId: string, text: string, priority: TaskPriority) => {
    const { data: { user } } = await supabase.auth.getUser()
    await supabase.from('tasks').insert({ product_id: productId, text, priority, created_by: user?.id })
  }

  const toggleTask = async (id: number, done: boolean) => {
    await supabase.from('tasks').update({ done, done_at: done ? new Date().toISOString() : null }).eq('id', id)
  }

  const deleteTask = async (id: number) => {
    await supabase.from('tasks').delete().eq('id', id)
  }

  const addLog = async (productId: string, content: string) => {
    const { data: { user } } = await supabase.auth.getUser()
    await supabase.from('session_logs').insert({ product_id: productId, content, created_by: user?.id })
  }

  const deleteLog = async (id: number) => {
    await supabase.from('session_logs').delete().eq('id', id)
  }

  const updateProduct = async (id: string, updates: Partial<Pick<Product, 'status' | 'phase_note' | 'base_progress'>>) => {
    await supabase.from('products').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', id)
  }

  return (
    <DashboardCtx.Provider value={{ tasks, logs, products, loading, pct, addTask, toggleTask, deleteTask, addLog, deleteLog, updateProduct }}>
      {children}
    </DashboardCtx.Provider>
  )
}

export function useDashboard() {
  const ctx = useContext(DashboardCtx)
  if (!ctx) throw new Error('useDashboard must be used inside DashboardProvider')
  return ctx
}
