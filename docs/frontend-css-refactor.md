# Frontend CSS maintenance

Last measured on 2026-11-18 from `main`.

## Current size

| File | Lines | Characters |
|---|---:|---:|
| `frontend/src/styles.css` | 1,788 | 182,242 |
| `frontend/src/tokens.css` | 110 | 3,194 |
| **Combined** | **1,898** | **185,436** |

The original measurement for this cleanup was 9,428 combined lines and 255,060 characters. The current source is 7,530 lines shorter, largely because CSS declarations and selectors were compacted to one rule per line. Character count is down by 69,624 (about 27.3%). Line count must not be treated as a proxy for runtime CSS complexity.

Current source checks:
- 40 media-query blocks.
- 801 `!important` occurrences.
- No empty CSS rules.
- Theme variables are centralized in `tokens.css`; the earlier unused amber variables were removed.
- The separate tablet layout was removed in commit `485261c`. Tablets up to 1024px use the mobile composition; desktop starts at 1025px. Narrow-desktop refinements are not a third layout.

## Cleanup already completed

- Moved the canonical light/dark theme variables into `tokens.css`.
- Removed retired credential and teacher-toggle styles.
- Removed identical and provably superseded declarations after checking selector, specificity, media context and source order.
- Removed obsolete generic graph styles that were replaced by graph-specific rules.
- Merged identical rule blocks only where the cascade remained unchanged.
- Removed empty rules and stale tablet-only comments.
- Preserved dynamic role classes and conditional modal/expanded classes.
- Added frontend production-build and design-token lint checks to GitHub Actions.

## Safety rules for future edits

1. Edit the existing component rule in place; do not append corrective overrides to the end of the stylesheet.
2. Do not reorder rules just to group them.
3. Do not remove a declaration based only on a later declaration that looks similar. Check specificity, media/theme conditions, pseudo-states and intervening rules.
4. Keep the two layout modes: mobile (up to 1024px) and desktop (from 1025px).
5. Require a production build and light/dark visual checks at mobile and desktop widths before considering structural CSS work complete.

## Remaining work

The stylesheet still has substantial component-specific styling and 801 `!important` occurrences. Further large reductions require component-by-component consolidation with screenshot coverage. Do not chase a line-count target by deleting live states or flattening distinct behavior.
