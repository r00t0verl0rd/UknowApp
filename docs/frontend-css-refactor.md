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

## Completed foundation and history-based cleanup

- Extracted the light and dark theme roots into one canonical base and one dark override in `tokens.css`, preserving the effective values after the old scattered overrides.
- Reviewed the stylesheet history and current React markup. Removed retired credential styles (`.password-actions`, `.password-code-label`) and the old `.teacher-toggle` implementation remnants.
- Removed 289 identical repeated declarations and 850 earlier declarations superseded by later declarations for the same selector in the same media context.
- Removed 94 more superseded declarations that were hidden inside grouped selector lists.
- Pruned 130 fully superseded selectors from 55 grouped rules; a selector was removed only when every declaration for it was supplied by a later rule with the same selector and context.
- Removed empty rules left by the cascade cleanup, merged five adjacent responsive wrappers, nine adjacent groups with identical declarations, and two adjacent teacher-graph rules.
- Static verification against `App.jsx` and `MessageBubble.jsx`: 170 distinct CSS class tokens, none absent from those source files; no empty style rules; no remaining retired credential/toggle selectors.

### Current measured size (main, 2026-11-18)

| File | Lines | Characters |
|---|---:|---:|
| `styles.css` | 7,887 | 204,179 |
| `tokens.css` | 113 | 3,264 |
| **Combined** | **8,000** | **207,443** |

Compared with the combined starting point for this pass (9,428 lines / 255,060 characters), the source is down by 1,428 lines (15.1%) and 47,617 characters (18.7%). The requested 3x reduction has **not** been reached. The remaining 4,324 declarations include real layout, responsive, media, and theme behavior; reaching a third of the current size safely will require component-level simplification and visual regression coverage, not blind deletion or minification.

Current structural counts: 1,612 parsed style rules, 41 media-query blocks and 817 `!important` declarations. These are source counts, not a runtime CSS coverage report.

No production build or light/dark mobile/tablet/desktop visual regression run has been performed for this cleanup.

## Next phases

1. Map the remaining responsive rules by component and viewport range, then consolidate each component's base, tablet/mobile and dark-theme treatment in place.
2. Review high-specificity and `!important` use by component, keeping only cases with a demonstrated cascade requirement.
3. Establish screenshot fixtures and a reproducible demo dataset before changing the visual rules more aggressively.
4. Replace repeated component-specific values with semantic tokens and shared component rules only where their behavior is genuinely the same.
5. Reassess file size after each component migration; retain the 3x goal as a target, not a reason to remove required behavior.
