-- Decoded Empire Dashboard schema
-- Run this in Supabase SQL editor (Dashboard > SQL Editor > New query)

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#1D9E75',
  bg_color TEXT NOT NULL DEFAULT '#E1F5EE',
  text_color TEXT NOT NULL DEFAULT '#085041',
  base_progress INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Backlog'
    CHECK (status IN ('Building', 'Planning', 'Active', 'Backlog', 'Done')),
  phase_note TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'mid'
    CHECK (priority IN ('high', 'mid', 'low')),
  done BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  done_at TIMESTAMPTZ,
  created_by UUID REFERENCES auth.users(id)
);

CREATE TABLE IF NOT EXISTS session_logs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by UUID REFERENCES auth.users(id)
);

-- Row Level Security
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "products_select" ON products FOR SELECT TO authenticated USING (true);
CREATE POLICY "products_insert" ON products FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "products_update" ON products FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "products_delete" ON products FOR DELETE TO authenticated USING (true);

CREATE POLICY "tasks_select" ON tasks FOR SELECT TO authenticated USING (true);
CREATE POLICY "tasks_insert" ON tasks FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "tasks_update" ON tasks FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "tasks_delete" ON tasks FOR DELETE TO authenticated USING (true);

CREATE POLICY "logs_select" ON session_logs FOR SELECT TO authenticated USING (true);
CREATE POLICY "logs_insert" ON session_logs FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "logs_update" ON session_logs FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "logs_delete" ON session_logs FOR DELETE TO authenticated USING (true);

-- Seed products
INSERT INTO products (id, name, color, bg_color, text_color, base_progress, status, phase_note, sort_order)
VALUES
  ('cloud-decoded',  'Cloud Decoded',  '#1D9E75', '#E1F5EE', '#085041', 85, 'Building', 'MVP built - deploy blockers: Supabase, Stripe IDs, hosting, DNS, auth pages', 1),
  ('gta-6-hub',      'GTA 6 Hub',      '#378ADD', '#E6F1FB', '#0C447C',  5, 'Planning', 'Domain + scaffold next - Week 1 priority', 2),
  ('ceo-decoded',    'CEO Decoded',    '#7F77DD', '#EEEDFE', '#3C3489', 10, 'Backlog',  'Internal agents first, product later', 3),
  ('hustle-decoded', 'Hustle Decoded', '#D85A30', '#FAECE7', '#712B13', 10, 'Active',   'LinkedIn + YouTube - run parallel always', 4),
  ('micro-saas',     'Micro SaaS',     '#BA7517', '#FAEEDA', '#633806',  0, 'Backlog',  'GTA Hub is product #1 on the engine', 5),
  ('career',         'Career',         '#639922', '#EAF3DE', '#27500A', 20, 'Active',   'Interview prep + higher-paying role search', 6)
ON CONFLICT (id) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_product_id ON tasks(product_id);
CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_product_id ON session_logs(product_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON session_logs(created_at);
