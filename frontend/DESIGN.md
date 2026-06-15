# Design system — Yield Analysis frontend

This is the contract for how the UI looks and how to change it safely. Read it
before touching any styling. It exists because "just improve the UI" with no
boundary is how working things get broken.

## The one rule that prevents regressions

**Restyle only. Never change behavior in the same edit.**

- Allowed in a styling change: CSS values, class names on existing elements,
  purely presentational markup (wrappers, an icon, an empty-state block).
- NOT allowed in a styling change: state (`useState`), data fetching, the SSE
  event handling in `run()`, props, event handlers, the turn/trace logic, the
  export flow. If you think a restyle needs one of these, stop and make it a
  separate, explicit change.
- **Class names are the API between JSX and CSS.** If you rename a class, change
  it in BOTH `*.jsx` and `styles.css` in the same edit, or something renders
  unstyled. When in doubt, keep the class name and change its CSS.

### Workflow for any UI change
1. Frontend is committed clean → `git checkout frontend/` reverts anything.
2. Change one view/section at a time.
3. Restyle only (see above).
4. Run the app, screenshot, compare against before.
5. Commit that step before starting the next.

## Tokens (defined in `:root` in `styles.css`)

Use the variables. Do not hardcode hex values or pixel font-sizes in new rules —
reach for a token so the system stays consistent.

### Color
Neutral base, green as the **single action accent**. Green means "you can act
here" (primary buttons, active/selected state, key numbers) — it is NOT a
decoration. If everything is green, nothing reads as the action.

- `--bg` app background (neutral, not green-tinted)
- `--surface` / `--surface-2` cards / insets (feed, list boxes)
- `--line` / `--line-strong` borders
- `--text` / `--text-2` / `--muted` — three-step text hierarchy (headings / body / secondary)
- `--accent` / `--accent-deep` / `--accent-weak` / `--accent-line` — the green action color + its hover/selected tints
- Semantic: `--warn*`, `--err*`, `--think*` (each has a text + bg + line)

### Type scale (no other sizes)
`--fs-2xs 11` · `--fs-xs 12` · `--fs-sm 13` · `--fs-base 14` · `--fs-md 15` ·
`--fs-lg 17` · `--fs-xl 21` · `--fs-2xl 28`. Line-height `--lh-tight 1.25`,
`--lh 1.5`.

### Spacing scale (multiples of 4)
`--sp-1 4` · `--sp-2 8` · `--sp-3 12` · `--sp-4 16` · `--sp-5 20` · `--sp-6 24` ·
`--sp-8 32`.

### Radius / elevation / focus
Radius: `--r-sm 7` · `--r-md 10` · `--r-lg 14` · `--r-xl 18` · `--r-pill 999`.
Shadow: `--sh-sm` (resting card) · `--sh-md` (raised card) · `--sh-pop` (menus) ·
`--sh-lg` (modals). Focus ring: `--ring`.

## Layout

- `.app.app-wide` caps width and uses most of the viewport; the investigate view
  adds `.app-fixed` so the **page never scrolls — each column scrolls itself**.
  Keep that invariant: heights flow through flex/`min-height:0`, not magic pixel
  offsets.
- Investigate = 3 columns: `.setup` (config) · `.center` (conversation) ·
  `.feed` (orchestrator trace). Collapsible via `.no-setup` / `.no-trace`.
- Below 820px everything stacks to one column (media query at the bottom of
  `styles.css`). Test narrow before shipping.

## Empty states are first impressions, not dead space

The center's empty state (`.empty-hero`) is the landing: a mark, a title, a
one-line explainer, and the suggested starters (`.starter-chip`) grouped right
there — not floating at the bottom. Any new empty area (feed, lists) gets the
same treatment: say what will appear and, where possible, offer the first action.

## Component conventions

- **Buttons**: default = neutral outline; `.primary` = accent fill (the main
  action only); `.ghost` = transparent; `.mini` = small toolbar button.
- **Chips/pills**: neutral by default, accent tint only when `.on`/selected.
- **Cards** (`.card`): white surface, `--r-lg`, `--sh-md`.
- **Messages**: `.msg.user` accent bubble (right), `.msg.assistant` white card
  (left). Markdown renders inside `.md`.
- **Trace events** (`.ev.*`): the tag color encodes the event type
  (tool=green, final=filled green, thinking=purple, warn/err=semantic). Keep
  that mapping — it's how the trace stays scannable.
