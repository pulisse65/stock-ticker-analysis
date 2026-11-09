-- PEAD book (post-earnings drift, pre-registered 2026-11-08, see PEAD_BOOK.md).
-- One row per paper STOCK order, plus one 'scan' marker row per session.
--
-- ⚠️ RUN THIS BEFORE SETTING PEAD_ENABLED=1 — entries log here and use the
-- per-session marker to evaluate once per day; exits pair sell rows to buy
-- rows via parent_id.
--
-- Run once in the Supabase SQL editor.

create table if not exists pead_trades (
  id               uuid primary key default gen_random_uuid(),
  ts               timestamptz not null default now(),
  session_key      text        not null,          -- ET session date of the action
  symbol           text        not null,          -- '*' on the scan marker row
  side             text        not null,          -- 'buy' | 'sell' | 'scan'
  qty              integer     not null default 0,
  est_price        numeric,                       -- reaction close used for sizing
  fill_price       numeric,                       -- filled later by reconciliation
  reason           text,
  z                numeric,                       -- reaction / sigma60 (buy rows)
  event_date       date,                          -- earnings report date (buy rows)
  reaction_session date,                          -- session whose close carried the reaction
  exit_session     date,                          -- planned exit session (buy rows)
  parent_id        uuid,                          -- sell rows: the buy row they close
  alpaca_order_id  text,
  alpaca_status    text,
  raw              jsonb
);
create index if not exists pead_trades_session_idx on pead_trades (session_key);
create index if not exists pead_trades_parent_idx on pead_trades (parent_id);
