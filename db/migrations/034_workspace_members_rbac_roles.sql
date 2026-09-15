-- Migration 034 — Real RBAC roles on workspace_members
-- Membership/SSO/RBAC/SCIM plan, Phase C.
--
-- Migration 033 shipped role as a generic 'admin' | 'member' pair (Phase
-- A's own bootstrap need: something to gate invite-permission on). Phase
-- C maps role onto real product actions per the plan: admin (full
-- control incl. invite/settings), approver (can approve/reject incident
-- remediations), viewer (read-only). 'member' becomes 'viewer' -- same
-- non-privileged default, now named for what it actually grants instead
-- of a placeholder. workspace_members.role is VARCHAR(50), not an enum,
-- so this is a data fixup + default change, not a type migration.
--
-- Safe to run even though no real invites have gone out through this
-- table yet (Phase A shipped hours before this migration in the same
-- build) -- defensive, not assuming that.

UPDATE workspace_members SET role = 'viewer' WHERE role = 'member';

ALTER TABLE workspace_members ALTER COLUMN role SET DEFAULT 'viewer';
