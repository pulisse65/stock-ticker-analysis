-- Small key/value store for "did we already do this" markers that must
-- survive a redeploy: the live-halt Slack alert, the daily and weekly retro
-- posts. Before this, those guards lived in process memory, so every deploy
-- re-posted them (eight deploys in the week of 2026-10-21 = eight repeats).
--
-- Run once in the Supabase SQL editor. The app falls back to in-memory
-- guards if the table is missing.

create table if not exists app_state (
  key        text primary key,
  value      jsonb,
  updated_at timestamptz not null default now()
);
