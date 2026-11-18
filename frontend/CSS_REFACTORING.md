# CSS refactoring baseline

Baseline captured from `main` after commit `27fd315` (18 November 2026).

## Current inventory

These figures are static-source measurements; the app was not launched and no visual-regression screenshots were captured.

- `frontend/src/styles.css`: 9,418 lines, about 255 KB of source.
- Approximately 1,844 CSS rule blocks, including media-query-contained rules.
- 51 media-query blocks.
- 923 occurrences of `!important`.
- 1,209 hexadecimal color literals.
- 439 selectors scoped to `:root[data-theme="dark-soft"]`.
- 317 selector strings occur more than once; those repeated groups account for 1,170 rule occurrences.
- Most repeated selectors include `.user-row` (21), `.content` (16), `.chat-list` (16), and `.user-actions` (13).
- No exact duplicate property/value pair was found within an individual simple rule block by a conservative source scan. This does not rule out duplicates across separate rules or selectors with different specificity.

## Safety constraints

1. Do not reorder rules merely to group selectors. The current cascade depends on source order and specificity.
2. Do not delete a declaration because another selector appears to override it; compare selector specificity, pseudo-states, media conditions, and theme conditions first.
3. Keep each cleanup limited to one component or one mechanically provable class of redundancy.
4. Keep responsive and dark-theme behavior adjacent to the component as components are migrated.
5. Do not add new corrective override blocks to the end of `styles.css`. Edit the component's existing source rules.
6. Treat visual parity as unverified until screenshots are captured at 390, 820, and 1440 px in both themes for the login, directory/graph, and chats views.

## Phases

- [ ] Capture visual baselines for 3 views × 2 themes × 3 widths.
- [ ] Parse the stylesheet and map selector occurrences with their enclosing media/theme conditions.
- [ ] Remove only mechanically proven redundant declarations and merge rules only where cascade order is preserved.
- [ ] Introduce semantic color tokens and migrate one component at a time.
- [ ] Reduce specificity and `!important` component by component.
- [ ] Move responsive rules next to their components and consolidate breakpoints after visual checks.
- [ ] Split the stylesheet into tokens, base, shell, and component stylesheets.
- [ ] Add linting/CI guardrails once the legacy baseline has been brought under control.

## First cleanup

The teacher credentials panel had accumulated multiple appended overrides. Its current layout declarations have been moved into its original component rules, and the appended teacher-only override blocks were removed. This reduced the stylesheet from 9,550 to 9,418 lines without changing JSX or the credential behavior.

The next safe step is a full selector/context inventory, followed by a single-component cleanup with visual comparison.