# Review brief — vertical collapsible navigation (branch `side-nav`)

**Ask from Paul (2026-10-29):** "make the UI have vertical tabs vs horizontal
and have it be collapsable."

## What changed (index.html only)

- The nine tab buttons moved out of the sticky header into a left
  `<aside id="side-nav">` beside `<main>`, inside a `md:flex` wrapper.
  Each button keeps `class="tab-btn" data-tab="…"`, so `setTab()`, the
  URL-hash routing, localStorage tab persistence and the 60-second
  auto-refresh are untouched.
- Each tab has a 16px inline SVG icon plus a `.tab-label` span. A "Menu"
  toggle at the top collapses the rail to 48px (icons only, `title` tooltips)
  and persists in `localStorage["ui.navCollapsed"]`. `aria-expanded` and the
  button label flip with state.
- Sidebar is `position: sticky; top: 72px` with its own scroll if the
  viewport is short.
- Below 768px the aside becomes the old horizontal scroll strip above the
  content (labels only, icons hidden, toggle hidden); the collapsed state is
  ignored there.
- Active state: left 3px brand border + hover background instead of the
  bottom border.

## Verified locally

Expanded, collapsed, and 375px mobile renders; collapsed state survives a
reload; `#trading` deep link lands on the right tab with the rail collapsed.
No JS changes beyond the toggle block next to the tab click wiring.

## What to look at

1. Visual weight of the rail against the cards: too heavy / too light?
2. Sticky offset (72px) against the header height on both themes.
3. Icon choices per tab (Alerts bell, Trading trend, Bullseye target,
   Analysis bars, Dashboard grid, Quotes list, Sectors pie, Movers pulse, AI
   sparkle).
4. Mobile strip: should Learn (`#learn`, reachable only via the help button)
   get a tab there?
5. Keyboard: tab order is toggle → tabs → content; is focus styling visible
   enough on the rail?
