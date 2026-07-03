export type TaskPriority = 'high' | 'mid' | 'low'
export type ProductStatus = 'Building' | 'Planning' | 'Active' | 'Backlog' | 'Done'
export type TabId = 'overview' | 'tasks' | 'products' | 'sessions'

export interface Product {
  id: string
  name: string
  color: string
  bg_color: string
  text_color: string
  base_progress: number
  status: ProductStatus
  phase_note: string
  sort_order: number
}

export interface Task {
  id: number
  product_id: string
  text: string
  priority: TaskPriority
  done: boolean
  created_at: string
  done_at: string | null
}

export interface SessionLog {
  id: number
  product_id: string
  content: string
  created_at: string
}
