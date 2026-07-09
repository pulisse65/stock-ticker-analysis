-- Multi-strategy expansion: generalize purgatory_* tables with a `strategy`
-- column. All legacy rows become 'purgatory'.
--
-- ⚠️ RUN THIS BEFORE DEPLOYING THE MULTI-STRATEGY CODE.
-- The new code upserts signals with on_conflict="strategy,ticker,signal,bar_time",
-- which errors until the new unique constraint exists. (Old code keeps working
-- after the migration — the columns are additive with defaults — so migrate
-- first, deploy second.)
--
-- Run once in the Supabase SQL editor.

-- ---------- signals ----------
alter table purgatory_signals
  add column if not exists strategy text not null default 'purgatory';
alter table purgatory_signals
  add column if not exists meta jsonb;

-- Swap the (ticker, signal, bar_time) unique for one that includes strategy.
-- Constraint name varies by how the table was created, so find it by its
-- column set instead of guessing.
do $$
declare
  cname text;
begin
  select c.conname into cname
  from pg_constraint c
  join pg_class t on t.oid = c.conrelid
  where t.relname = 'purgatory_signals'
    and c.contype = 'u'
    and (
      select array_agg(a.attname order by a.attname)
      from unnest(c.conkey) k
      join pg_attribute a on a.attrelid = t.oid and a.attnum = k
    ) = array['bar_time','signal','ticker']::name[];
  if cname is not null then
    execute format('alter table purgatory_signals drop constraint %I', cname);
  end if;
end $$;

alter table purgatory_signals
  drop constraint if exists purgatory_signals_strategy_ticker_signal_bar_time_key;
alter table purgatory_signals
  add constraint purgatory_signals_strategy_ticker_signal_bar_time_key
  unique (strategy, ticker, signal, bar_time);

create index if not exists idx_signals_strategy_time
  on purgatory_signals (strategy, bar_time desc);

-- ---------- orders ----------
alter table purgatory_orders
  add column if not exists strategy text not null default 'purgatory';
create index if not exists idx_orders_strategy_time
  on purgatory_orders (strategy, submitted_at desc);

-- ---------- daily summaries ----------
-- (Table is purgatory_daily_summaries, not purgatory_summaries as in the spec.)
alter table purgatory_daily_summaries
  add column if not exists per_strategy jsonb;
