# Frontend CSS refactor

## Baseline (main, 2026-11-18)

Measured from `frontend/src/styles.css` before this refactor:

- 9,418 lines and 255,059 characters.
- 1,843 selector occurrences.
- 923 `!important` declarations.
- 49 media-query blocks.
- 226 selectors beginning with the dark-theme root selector.
- 1,209 hex color occurrences and 704 distinct hex values.
- 390 `var(...)` references.
- Most repeated selectors: `.user-row` (18), `.content` (16), `.chat-list` (15), `.user-actions` (13), `.chat-head` (12).

These are lexical counts, not a parsed CSS dependency graph. Repeated selectors are not automatically dead code: source order, specificity, media conditions, pseudo-states and `!important` can all affect the cascade.

## Safety constraints

- Preserve rule order until visual regression coverage exists.
- Do not remove declarations solely because a later declaration appears to override them.
- Keep the current visual palette unchanged while moving its definitions.
- Treat every structural CSS change as requiring a production build and visual checks in light/dark themes at mobile, tablet and desktop widths.
- Do not claim screenshot or runtime validation unless those checks were actually run.

## Completed foundation

- Extracted the global light and dark theme roots into `tokens.css`.
- Kept legacy token names and their current effective values so existing selectors continue to resolve without mass edits.
- Imported tokens before component styles; all remaining selectors stay in their original order.

## Next phases

1. Establish screenshot fixtures and a reproducible demo dataset.
2. Introduce semantic aliases for surfaces, text, borders, role colors and states; migrate components in small batches.
3. Consolidate each component's base, responsive and dark-theme rules without changing cascade order accidentally.
4. Reduce specificity and `!important` only where the owning component can be verified.
5. Split the stylesheet by responsibility after dependencies are mapped.
6. Add Stylelint and CI gates incrementally, starting with newly introduced CSS and token files rather than failing the legacy baseline immediately.
