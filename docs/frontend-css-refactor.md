# Frontend design system

Last measured on 2026-11-21 from `main`.

## Architecture

`frontend/src/shared/styles/index.css` is the single frontend stylesheet entry point. It loads the canonical theme tokens first, then ordered style modules:

| Module | Responsibility |
|---|---|
| `tokens.css` | Semantic colors, light/dark themes, typography, spacing, radii, control sizes, transitions and z-index |
| `base.css` | Global reset and foundational layout rules |
| `conversations.css` | Conversation list, message bubbles, media and composer |
| `structure.css` | Initial structure graph and role surfaces |
| `workspace.css` | Workspace shell, navigation, viewport and responsive layout refinements |
| `components.css` | Shared control states, buttons, inputs, dialogs, user-directory layout and action groups |
| `theme.css` | Shared surface and role palette refinements |
| `administration.css` | Administration data tools and push controls |
| `application.css` | Board-specific and standalone-app refinements |

The modules preserve the original source order. Later blocks still refine earlier selectors; the import order is therefore intentional and must not be alphabetized or changed casually. This split replaces the former monolithic `layout.css`; there is no second legacy stylesheet loaded in parallel.

## Shared React primitives

The reusable UI primitives live in `frontend/src/shared/components`:

- `Button`: shared button base with semantic variants and sizes.
- `IconButton`: shared icon-only action button.
- `Modal`: common overlay/dialog shell with backdrop-close control and dialog semantics.
- `Panel`: common workspace panel wrapper based on the existing graph-panel surface.
- `EmptyState`: common empty-content state.
- `AppToast`: shared application notification.

Feature components own their content and business behavior; the shared primitives own the common interaction and structural contract. Variants and extra classes are extension points, not copies of the base component.

## Design tokens

`tokens.css` is the only palette and theme source. It now includes shared families for:

- Typography: UI, heading and monospace font stacks, type sizes, weights and line heights.
- Spacing: a common 4px-based scale.
- Geometry: control heights, radii and icon-button size.
- Motion and stacking: transition durations and z-index levels.
- Semantic surfaces and feedback: application foreground/background, input and panel surfaces, placeholders, danger, success and warning.
- Existing brand and role palettes.

The dark theme overrides semantic variables under `:root[data-theme="dark-soft"]`. Components reference variables rather than choosing colors from React state.

## Current source measurements

| File group | Lines | Characters |
|---|---:|---:|
| Theme tokens | 189 | 5,522 |
| Ordered style modules | 705 | 149,427 |
| **Total** | **894** | **154,949** |

Current style inventory:
- 39 media-query blocks.
- 627 `!important` declarations remain.
- 186 selector groups appear more than once across the ordered modules. Some are responsive/theme variants; others are legacy refinements and need component-by-component cascade review.
- No unresolved CSS custom-property references in the stylesheet set.

The split is an organizational step, not a claim that every legacy override has already been eliminated. Removing the remaining important declarations or repeated selectors without checking source order, specificity, media conditions and theme variants could change existing layouts.

## Maintenance rules

1. Use an existing primitive and design token before adding a new local implementation.
2. Add new shared behavior to the appropriate component; keep feature content and business logic in its feature module.
3. Edit the existing rule in its owning style module rather than appending a corrective override to the last file.
4. Preserve the documented import order until a cascade-aware migration deliberately changes it.
5. Keep mobile and desktop composition rules shared where the behavior is shared; do not add a breakpoint-only copy merely to fix one component.
6. Check `min-width: 0`, overflow behavior, wrapping and text truncation for flex/grid children.
7. Require a production build and automated design-token check for CSS or component changes. Visual verification at mobile and desktop widths remains necessary for structural stylesheet changes.
