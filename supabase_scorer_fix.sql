-- Scorer mismatch fix: outcome scoring now anchors at alerted_at with a
-- realistic entry price, and classifies win/flat/loss net of an estimated
-- round-trip spread cost. These columns record how each row was scored so
-- old-regime and new-regime rows can be told apart in analysis.
--
-- ⚠️ RUN THIS BEFORE DEPLOYING THE SCORER-FIX CODE — the backfill update
-- writes these columns and the whole update fails if they don't exist
-- (outcomes would stay null forever).
--
-- Run once in the Supabase SQL editor.

alter table purgatory_signals
  add column if not exists scored_from text,               -- 'alerted_at' | 'bar_time'
  add column if not exists entry_exec_price numeric,       -- first 1-min close at/after the anchor
  add column if not exists entry_slippage_pct numeric,     -- favorable-direction move bar-close → exec (positive = alert delay cost)
  add column if not exists spread_cost_pct numeric;        -- SIGNAL_SPREAD_COST_PCT applied at scoring time
