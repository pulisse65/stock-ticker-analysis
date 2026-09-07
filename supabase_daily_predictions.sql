-- External daily predictions (bullseye): multi-day BUY/HOLD/SELL calls on
-- stocks, posted by an off-box model runner and scored here against
-- realized daily closes once target_date has printed.
--
-- One row per (source, ticker, as_of_date). Rows are immutable once posted
-- (the ingest endpoint does ON CONFLICT DO NOTHING) so a prediction can't be
-- quietly revised after the outcome is known.
--
-- ⚠️ RUN THIS BEFORE DEPLOYING THE DAILY-PREDICTIONS CODE — the ingest
-- endpoint upserts into this table and the scorer updates it.
--
-- Run once in the Supabase SQL editor.

create table if not exists daily_predictions (
  id                 uuid primary key default gen_random_uuid(),
  source             text        not null default 'bullseye',
  model              text,                      -- e.g. 'small-classifier-nb'
  ticker             text        not null,
  as_of_date         date        not null,      -- last daily bar the features saw
  target_date        date        not null,      -- as_of + horizon business days
  forecast           text        not null,      -- 'buy' | 'hold' | 'sell'
  conf_buy           numeric,
  conf_hold          numeric,
  conf_sell          numeric,
  ref_price          numeric,                   -- close on as_of_date as the runner saw it
  meta               jsonb,
  -- true when posted well after as_of_date (walk-forward replay), so honest
  -- forward-only hit-rate views can exclude it
  backfilled         boolean     not null default false,
  submitted_at       timestamptz not null default now(),
  -- scoring — filled by the server once target_date's close exists
  scored_at          timestamptz,
  entry_close        numeric,                   -- close on as_of_date (first at/after)
  entry_close_date   date,
  target_close       numeric,                   -- first close at/after target_date
  target_close_date  date,
  realized_pct       numeric,                   -- (target_close - entry_close) / entry_close * 100
  actual             text,                      -- realized label under the same BUY/SELL cut-offs
  correct            boolean,                   -- actual == forecast
  direction_correct  boolean,                   -- buy→up / sell→down / hold→inside band
  score_note         text,                      -- set when a row is marked unscorable
  unique (source, ticker, as_of_date)
);

create index if not exists daily_predictions_pending_idx
  on daily_predictions (target_date) where scored_at is null;
create index if not exists daily_predictions_source_asof_idx
  on daily_predictions (source, as_of_date desc);
