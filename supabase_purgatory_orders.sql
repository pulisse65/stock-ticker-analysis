-- Purgatory Method: auto-trade order log
--
-- Every entry AND exit is a row. Entry rows are inserted on signal fire;
-- exit rows are inserted by the 30-min sweep. Match by
-- (signal_ticker, signal_direction, signal_bar_time) to compute per-trade P&L.
--
-- Run this once in the Supabase SQL editor.

create table if not exists purgatory_orders (
  id                 uuid primary key default gen_random_uuid(),
  -- Loose FK to purgatory_signals (matched by natural key, not id)
  signal_ticker      text        not null,
  signal_direction   text        not null,      -- 'call' | 'put'
  signal_bar_time    text        not null,      -- ISO timestamp
  -- Contract details
  option_symbol      text,                      -- OCC (e.g. AAPL251230C00195000)
  option_strike      numeric,
  option_expiration  date,
  option_type        text,                      -- 'call' | 'put'
  underlying_price   numeric,                   -- spot at entry
  -- Order details
  side               text        not null,      -- 'buy' | 'sell'
  role               text        not null,      -- 'entry' | 'exit'
  qty                integer,
  alpaca_order_id    text        unique,
  alpaca_status      text,                      -- 'accepted' | 'filled' | 'canceled' | 'rejected' | 'pending_new' | 'no_position'
  fill_price         numeric,                   -- per-contract avg fill (dollars, NOT cents)
  notional           numeric,                   -- fill_price * qty * 100
  submitted_at       timestamptz not null default now(),
  filled_at          timestamptz,
  paper              boolean     not null default true,
  raw                jsonb,
  created_at         timestamptz not null default now()
);

create index if not exists idx_purg_orders_signal
  on purgatory_orders (signal_ticker, signal_direction, signal_bar_time);
create index if not exists idx_purg_orders_submitted
  on purgatory_orders (submitted_at desc);
create index if not exists idx_purg_orders_status
  on purgatory_orders (alpaca_status);
create index if not exists idx_purg_orders_role_submitted
  on purgatory_orders (role, submitted_at desc);
