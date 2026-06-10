-- Migration: add cancellation audit trail to sales_invoices
-- Run once against existing databases. Safe to re-run (IF NOT EXISTS).
--
-- A cancelled invoice reverses a legally-issued document, so the action must be
-- traceable: who cancelled it, when, and why.

ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_by   INTEGER REFERENCES users(user_id);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_at   TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancel_reason  TEXT;
