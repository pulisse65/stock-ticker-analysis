export const meta = {
  name: 'live-promotion-sweep',
  description: 'Find signal pairs statistically worth promoting to live trading',
  phases: [
    { title: 'Lenses', detail: '4 parallel analysis lenses over signals + paper fills' },
    { title: 'Verify', detail: '3 adversarial skeptics per candidate' },
  ],
}

// BEFORE RERUNNING: review the PLATFORM FACTS block below — live pairs, disabled pairs,
// skip windows, muted strategies, and plan-scored strategies drift over time.
// Parameterized: pass {dataDir, python, dates} via Workflow args.
// dataDir must contain signals.csv / orders.csv / signals_raw.json / orders_raw.json
// (produced by analysis/pull_signals.py + analysis/pull_orders.py).
const SCRATCH = (args && args.dataDir) || './analysis/data'
const PY = (args && args.python) ? `"${args.python}"` : 'python3'
const DATES = (args && args.dates) || 'the collected sessions'

const CONTEXT = `
You are analyzing data from "Ticker Tracker", a 0DTE options signal platform, to decide which
(strategy, ticker, direction) pairs are statistically strong enough to promote to LIVE real-money
trading. Currently only purgatory:TSLA:call trades live. This is a statistics/engineering task —
compute honest numbers, do not give investment advice.

DATA FILES (already downloaded, read-only):
1. ${SCRATCH}/signals.csv — signal rows covering ${DATES}.
   Columns: strategy,ticker,direction,bar_time,alerted_at,price,scored_from,outcome,
   f5,f10,f15,f20,f25,f30,plan_outcome,plan_net_pct,plan_exit_reason,et_date,et_time,et_hour,et_minute,dow
   - CRITICAL FILTER: only rows with scored_from == 'alerted_at' are honestly scored .
     Rows with scored_from NaN are legacy/lookahead-scored — EXCLUDE them from all statistics.
   - outcome: 'win' = best favorable underlying move exceeded +0.10% net within 30 min of alert
     (net of 0.05% assumed spread cost); 'loss' = adverse; 'flat' = neither.
     Win rate convention on this platform: wins / (wins+losses+flats).
   - f5..f30 = favorable underlying move (%) at that horizon, GROSS. Net = f - 0.05.
     net_f15 is the platform's promotion-gate expectancy metric (the paper trader holds ~15 min).
2. ${SCRATCH}/orders.csv — CLOSED paper-account option round-trips (real Alpaca paper fills).
   Columns include: strategy,ticker,direction,bar_time,entry,exit,qty,pnl,pnl_at_mid,exit_reason,
   entry_quote,exit_quote,execution_drag,signal_outcome,date,et_time,dow.
   pnl is realized $ P&L per round-trip. Only the 'purgatory' strategy places trades.
3. ${SCRATCH}/signals_raw.json and ${SCRATCH}/orders_raw.json — full raw records incl. meta.

RUN PYTHON WITH: ${PY} yourscript.py   (pandas 3.0.2 available; write scripts into ${SCRATCH}/)

PLATFORM FACTS YOU MUST RESPECT:
- Live promotion = adding "strategy:TICKER:direction" to LIVE_TRADING_PAIRS. There is NO
  time-of-day or day-of-week conditioning in the live gate today (that would be a new feature).
- Only 'purgatory' is a trading strategy (has paper fills). All others are signals-only; promoting
  one would ALSO require adding it to STRATEGIES_TRADING — a bigger step. Note this on candidates.
- purgatory AVGO call+put are disabled (PURGATORY_DISABLED_PAIRS) — not eligible.
- purgatory:TSLA:call already trades live — EXCLUDE from candidates, but report its current
  record as the benchmark bar that any new candidate is compared against.
- bb_squeeze got skip windows ~8/13 (open_first_15, lunch_chop, early_afternoon_chop, close_chop);
  its pre-8/13 signals include time windows it can no longer fire in.
- orb_ntz is plan-scored: its generic outcome/f15 metrics are known-misleading (signals carry their
  own stop/target plan; see plan_outcome/plan_net_pct — only ~4 plan verdicts exist so far).
- vwap_reclaim was auto-muted by the kill gate (wr<35% at n>=30) — data exists, strategy is dead.
- The paper trader: buys nearest-expiry ATM option, holds 15 min, 30% stop loss.
- Wilson 95% lower bound: p̂ + z²/2n minus z·sqrt(...) over (1+z²/n), z=1.96. Compute it exactly.

CANDIDATE BAR (to nominate): n >= 8 honest-scored signals in the slice, win_rate >= 60%,
wilson_lo >= 0.45, and avg net_f15 > 0 for the slice. Nominate at most your 4 strongest.
A candidate may be a whole pair OR a pair restricted to a time window / day-of-week (report the
restriction in 'window'/'dow' fields — but remember restricted candidates need new gating code).

Your final structured output: 'summary' = a dense, number-rich report of everything you found
(readable by someone who has not seen the data), plus 'candidates' array.
`

const LENS_SCHEMA = {
  type: 'object',
  required: ['summary', 'candidates'],
  properties: {
    summary: { type: 'string' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['strategy', 'ticker', 'direction', 'n', 'wins', 'losses', 'flats', 'win_rate', 'wilson_lo', 'net_f15', 'evidence'],
        properties: {
          strategy: { type: 'string' },
          ticker: { type: 'string' },
          direction: { type: 'string', enum: ['call', 'put'] },
          window: { type: 'string', description: "ET time window restriction like '09:45-11:30', or 'all'" },
          dow: { type: 'string', description: "day-of-week restriction like 'Mon-Thu', or 'all'" },
          n: { type: 'integer' },
          wins: { type: 'integer' },
          losses: { type: 'integer' },
          flats: { type: 'integer' },
          win_rate: { type: 'number' },
          wilson_lo: { type: 'number' },
          net_f15: { type: 'number' },
          net_f30: { type: 'number' },
          paper_pnl: { type: 'number', description: 'realized paper $ P&L for this slice if trading strategy, else 0' },
          evidence: { type: 'string' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['refuted', 'confidence', 'reasoning', 'key_numbers'],
  properties: {
    refuted: { type: 'boolean', description: 'true if this candidate should NOT go live' },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    reasoning: { type: 'string' },
    key_numbers: { type: 'string' },
  },
}

const LENSES = [
  {
    key: 'pairs',
    prompt: `${CONTEXT}
YOUR LENS: whole-pair conviction. For every (strategy,ticker,direction) with n>=5 honest-scored
signals, compute n, W/L/F, win_rate, Wilson 95% lower bound, avg net_f15, avg net_f30, and the
number of distinct sessions the signals span. Print the full ranked table in your summary
(win_rate desc within n>=8). Report purgatory:TSLA:call's current full record as the benchmark
(including how it has done since 8/13). Nominate candidates per the bar. Also note any pair that
looks strong on win_rate but has negative net_f15 (scalper-metric mirage) — do NOT nominate those.`,
  },
  {
    key: 'timing',
    prompt: `${CONTEXT}
YOUR LENS: time-of-day and day-of-week. Bucket honest-scored signals into ET windows
(09:30-09:45, 09:45-10:30, 10:30-11:30, 11:30-13:00, 13:00-14:30, 14:30-15:30, 15:30-16:00) and
day-of-week. Compute win_rate + avg net_f15 per bucket: (a) pooled across all strategies,
(b) per strategy, (c) for the most active pairs (n>=12 total), per pair × window and pair × dow
where the slice has n>=8. Look specifically for: pairs that are mediocre overall but strong+positive-net
inside a window/dow slice, and pairs that are strong overall but have a toxic window dragging them.
Print the key tables in your summary. Nominate at most 4 window/dow-restricted candidates per the bar —
and for each, also report the pair's UNRESTRICTED record so we can see what the restriction buys.`,
  },
  {
    key: 'stability',
    prompt: `${CONTEXT}
YOUR LENS: stability and recency. For each pair with n>=8 honest-scored signals: split the record
into July (7/9-7/31) vs August (8/1-8/21) and into first-half vs second-half of its own signal
sequence; compute win_rate and net_f15 for each half. Flag pairs whose edge is concentrated in one
hot week or has decayed recently (compute per-week win rates for the top pairs). Also build a
per-session cumulative net_f15 curve for the top 5 pairs by win_rate (n>=10) and describe its shape
(steady grind vs one spike). Report purgatory:TSLA:call's week-by-week record as benchmark context.
Nominate only pairs whose edge is TEMPORALLY ROBUST (positive in both halves) per the bar; in
'evidence' state the half-split numbers.`,
  },
  {
    key: 'fills',
    prompt: `${CONTEXT}
YOUR LENS: realized paper option fills (orders.csv) — what actually happened when signals were traded.
For every purgatory pair: closed trades, sum(pnl), mean(pnl), median(pnl), win rate on fills
(pnl>0), exit_reason mix (hold_expired vs stop_loss), avg execution_drag, avg entry premium
(entry x 100 x qty / qty = entry*100 per contract), and pnl_at_mid vs pnl gap (slippage proxy).
Cross-check: for pairs where signal win_rate is high, did fills actually make money? Where do
signal metrics and fill P&L disagree, and why (spread, stop-outs, premium too rich)?
Also compute per-pair fill P&L by ET window (morning 09:45-11:30 vs after) and by dow if n allows.
Check whether any pair's P&L is dominated by 1-2 outlier trades (report top-2 trade share of total).
Print the full table in your summary. Nominate per the bar (use signal stats for the bar fields,
but ONLY nominate pairs whose fill P&L is positive and not outlier-dominated; put fill numbers in
'evidence' and paper_pnl).`,
  },
]

phase('Lenses')
log('Running 4 analysis lenses over the honest-scored signals + paper fills')
const lensResults = await parallel(
  LENSES.map(l => () => agent(l.prompt, { label: `lens:${l.key}`, phase: 'Lenses', schema: LENS_SCHEMA }))
)

// Barrier justified: candidate dedup/merge needs all lenses' nominations together.
const lensOk = lensResults.filter(Boolean)
const merged = new Map()
for (let i = 0; i < lensOk.length; i++) {
  for (const c of lensOk[i].candidates || []) {
    if (c.strategy === 'purgatory' && c.ticker === 'TSLA' && c.direction === 'call' && (!c.window || c.window === 'all') && (!c.dow || c.dow === 'all')) continue
    if (c.strategy === 'purgatory' && c.ticker === 'AVGO') continue
    const key = `${c.strategy}|${c.ticker}|${c.direction}|${c.window || 'all'}|${c.dow || 'all'}`
    const prev = merged.get(key)
    if (!prev || (c.n || 0) > (prev.n || 0)) merged.set(key, { ...c, nominatedBy: prev ? prev.nominatedBy + ',' + LENSES[i].key : LENSES[i].key })
    else prev.nominatedBy += ',' + LENSES[i].key
  }
}
const allCands = [...merged.values()].sort((a, b) => (b.wilson_lo || 0) - (a.wilson_lo || 0))
const toVerify = allCands.filter(c => (c.n || 0) >= 8).slice(0, 6)
log(`Lenses nominated ${allCands.length} unique candidates; verifying top ${toVerify.length}: ${toVerify.map(c => `${c.strategy}:${c.ticker}:${c.direction}${c.window && c.window !== 'all' ? '@' + c.window : ''}${c.dow && c.dow !== 'all' ? '/' + c.dow : ''}`).join(', ')}`)

phase('Verify')
const SKEPTICS = [
  {
    key: 'stats',
    angle: `You are a STATISTICS skeptic. Refute on statistical grounds: recompute the candidate's
numbers yourself from the data files (do not trust the claim). Consider multiple-comparisons /
selection bias — this candidate was picked as the best-looking cell out of roughly 100+ pair and
pair-x-window cells scanned, so a high win rate is expected somewhere by chance; ask whether the
Wilson lower bound and net expectancy still clear the bar under that selection pressure (e.g. would
it survive if you demand wilson_lo >= 0.55, or a simple binomial test against p=0.5 with a
Bonferroni-ish haircut). Check flats-as-wins issues: win_rate counts flats in the denominator, but
also verify net_f15/net_f30 are positive and not driven by 1-2 outlier signals (recompute median
net_f15 and trimmed mean).`,
  },
  {
    key: 'tradability',
    angle: `You are a TRADABILITY skeptic. Refute on execution grounds: the signal metric is
underlying % move, but real money buys ~ATM nearest-expiry options, holds 15 min, 30% stop. Use
orders.csv fills for this pair (if purgatory): realized $ P&L, stop-out rate, execution_drag,
pnl vs pnl_at_mid slippage, entry premium sizes vs the $500 live notional / $750 per-trade cap
(a contract over $750 skips the live leg — what fraction of this pair's fills had entry*100 > 750?).
If the candidate is window/dow-restricted: LIVE_TRADING_PAIRS cannot express that today — new code
required; weigh whether unrestricted trading of the pair would be acceptable (compute the pair's
unrestricted stats). If a signals-only strategy: no fill history exists at all — that alone is
strong grounds to refute going straight to live (it would also need STRATEGIES_TRADING promotion
and a paper track record first). orb_ntz additionally is plan-scored — generic win_rate is invalid.`,
  },
  {
    key: 'regime',
    angle: `You are a REGIME/STABILITY skeptic. Refute on robustness grounds: recompute the
candidate's record week-by-week and July-vs-August from the data. Refute if the edge is
concentrated in one hot week or has flipped negative in the most recent 2 weeks, if signals
cluster in <6 distinct sessions (session-level correlation makes n overstated — signals in the
same session move together), or if the slice's sessions all share one regime (e.g. all trend days).
Compute distinct-session count and best-single-session share of total wins. Compare against the
benchmark pair purgatory:TSLA:call whose promotion bar was ~94% over many sessions.`,
  },
]

const verified = await parallel(
  toVerify.map(c => () => {
    const cd = JSON.stringify(c)
    return parallel(
      SKEPTICS.map(s => () =>
        agent(
          `${CONTEXT}
CANDIDATE UNDER ADVERSARIAL REVIEW (nominated by lens(es): ${c.nominatedBy}):
${cd}

${s.angle}

Recompute everything from the data files yourself. Default to refuted=true when uncertain — this
gates real money. In 'key_numbers' give the exact recomputed figures your verdict rests on.`,
          { label: `verify:${s.key}:${c.ticker}:${c.direction}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' }
        )
      )
    ).then(votes => {
      const vs = votes.filter(Boolean)
      const refutes = vs.filter(v => v.refuted).length
      return { candidate: c, votes: SKEPTICS.map((s, i) => ({ skeptic: s.key, ...(votes[i] || { refuted: true, confidence: 'low', reasoning: 'skeptic agent failed', key_numbers: '' }) })), refutes, verdict: refutes === 0 ? 'SURVIVES' : refutes === 1 ? 'CONDITIONAL' : 'REJECTED' }
    })
  })
)

return {
  lensSummaries: LENSES.map((l, i) => ({ lens: l.key, summary: lensOk[i] ? lensResults[i].summary : 'AGENT FAILED' })),
  allNominated: allCands,
  verified: verified.filter(Boolean),
}