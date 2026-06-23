-- Migration 001 — Initial schema
-- KDavis Agentic Systems LLC — Cloud Decoded
-- Run: psql $DATABASE_URL -f db/migrations/001_initial_schema.sql

-- This migration is identical to db/schema.sql.
-- Future migrations increment the number and run only deltas.

\i db/schema.sql
