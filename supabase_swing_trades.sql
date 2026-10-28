-- Swing book (weekly cloud regime + 12-week momentum, pre-registered
-- 2026-10-27, see SWING_BOOK.md). One row per paper STOCK order placed by
-- the weekly rebalance, plus one 'rebalance' marker row per week.
--
-- ⚠️ RUN THIS BEFORE SETTING SWING_ENABLED=1 — the rebalance logs here and
-- uses the weekly marker row to run once per week.
--
-- Run once in the Supabase SQL editor.

create table if not exists swing_trades (
  id               uuid primary key default gen_random_uuid(),
  ts               timestamptz not null default now(),
  week_key         text        not null,          -- ISO Monday of the trading week
  symbol           text        not null,          -- '*' on the weekly marker row
  side             text        not null,          -- 'buy' | 'sell' | 'rebalance'
  qty              integer     not null default 0,
  est_price        numeric,                       -- prior Friday close used for sizing
  fill_price       numeric,                       -- filled later by reconciliation (optional)
  reason           text,
  alpaca_order_id  text,
  alpaca_status    text,
  raw              jsonb
);
create index if not exists swing_trades_week_idx on swing_trades (week_key);
create index if not exists swing_trades_ts_idx on swing_trades (ts);
