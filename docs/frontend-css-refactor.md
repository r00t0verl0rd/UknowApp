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
- Reviewed relevant Git history, including the earlier removal of the `.teacher-toggle` implementation. Removed its now-empty mobile media query and stale explanatory comment.
- Compared CSS class selectors with the current `App.jsx` and `MessageBubble.jsx` markup. Removed the retired `.password-actions` and `.password-code-label` rules, including their dark-theme and shared-button references.
- Current `styles.css`: 9,322 lines and 252,623 characters (down from 9,392 lines / 254,213 characters at the start of this cleanup pass).
- Static checks after cleanup: no empty CSS blocks; no class tokens absent from the current React markup; no remaining references to `.password-actions`, `.password-code-label` or `.teacher-toggle`.

The cleanup above is limited to selectors verified as unused against the current React source and a component implementation already removed in Git history. It does not treat repeated selectors or `!important` declarations as dead code.

## Next phases

1. Continue reviewing stylesheet history and current component markup to identify obsolete rules with clear evidence.
2. Consolidate component base, responsive and dark-theme rules in place, preserving effective cascade order.
3. Establish screenshot fixtures and a reproducible demo dataset before broader cascade changes.
4. Reduce specificity and `!important` only where the owning component and visual effect can be verified.
5. Introduce semantic aliases for surfaces, text, borders, role colors and states in small component batches.
6. Split the stylesheet by responsibility only after dependencies are mapped; keep Stylelint/CI scoped to the verified baseline until legacy CSS is cleaned.
