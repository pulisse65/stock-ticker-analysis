# Prompt to paste into ChatGPT (Sol)

You are reviewing a small retail options-signal system as a skeptical quant
reviewer. I'm attaching a folder: `REVIEW_BRIEF.md` (read it first, fully),
`REPLAY_RESULTS.md`, a set of CSV summary tables, two raw CSVs
(`signals.csv`, `orders.csv`), and a `raw/` directory of JSON snapshots from
the production API. The brief defines every column and every term.

Ground rules:
- Do not give me investment advice or tell me to buy or sell anything. I
  want statistics, methodology critique, and engineering recommendations.
- Work from the files. If you compute something, say which file and which
  filter you used, and show the number of rows. If a number in the brief
  does not reproduce from the data, flag it.
- Treat samples honestly. Small n, survivorship, multiple comparisons and
  look-ahead are the failure modes I care about most. Call them out even
  when the conclusion is one I'd like.
- Be direct. If something in the design is wrong, say so and say what you
  would do instead.

Please deliver, in this order:
1. A one-page verdict: what the data supports, what it does not, and the
   two or three biggest risks in how I'm reading it.
2. Answers to the eight questions in section 6 of the brief, each grounded
   in a specific table or computation.
3. A reproduction check: recompute the headline table in section 3 from
   `orders.csv` and the signal-level MSTR/AAPL records from `signals.csv`
   (honest rows only), and list any discrepancies.
4. One pre-registered experiment you would run next on paper for two weeks,
   with the exact decision rule written before the data comes in.
5. Anything I did not ask about that you think matters.
