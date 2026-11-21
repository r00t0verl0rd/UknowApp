# Frontend design system

Last measured on 2026-11-21 from `main`.

## Architecture

`frontend/src/shared/styles/index.css` is the single frontend stylesheet entry point. It loads `tokens.css` first, then feature and component style modules in the order shown below:

| Module | Responsibility |
|---|---|
| `tokens.css` | Semantic colors, light/dark themes, typography, spacing, radii, control sizes, transitions and z-index |
| `base.css` | Global reset and foundational layout rules |
| `conversations.css` | Conversation list, message bubbles, media and composer |
| `structure.css` | Structure graph primitives and initial graph layout |
| `inbox.css` | Shared inbox actions and teacher/student conversation surfaces |
| `graph-and-theme.css` | Graph workspace refinements and application theme rules |
| `workspace-layout.css` | Viewport sizing, workspace shell, navigation and responsive layout |
| `shared-controls.css` | Common button, input, modal and interaction states |
| `users.css` | User-directory rows, toolbar and responsive user controls |
| `workspace-refinements.css` | Final narrow-screen and action-group layout refinements |
| `theme.css` | Shared surface, palette and role refinements |
| `role-colors.css` | Shared student, teacher and administrator color language |
| `admin-tools.css` | Administration data tools, cleanup and backup UI |
| `board-objects.css` | Hierarchical board nodes, object actions and canvas |
| `standalone.css` | Installed-app safe-area treatment |

The modules are ordered extractions of the former stylesheet sections. Their concatenated source was checked against the previous files before those files were removed. Import order is intentional; do not alphabetize it. The old `layout.css`, `workspace.css`, `components.css`, `administration.css` and `application.css` files are no longer present.

## Shared React primitives

Reusable UI primitives live in `frontend/src/shared/components`:

- `Button`: shared button base with semantic variants and sizes.
- `IconButton`: shared icon-only action button.
- `FormField`: shared label, control and optional hint composition.
- `Modal`: common overlay/dialog shell with backdrop-close control and dialog semantics.
- `Panel`: common workspace panel wrapper based on the existing `graph-panel` surface.
- `EmptyState`: common empty-content state.
- `CountBadge`: shared unread and total counters with accessible labels and consistent overflow display.
- `AppToast`: shared application notification.

The user and conversation dialogs now use the same modal/button primitives; structure and conversation screens use the same empty-state component; counters in the structure legend and conversation navigation use the same badge. Boards and administration pages use the same panel primitive. Feature components still own content and business behavior; shared primitives own common structural and interaction contracts.

## Design tokens

`tokens.css` is the canonical palette and theme source. It includes:
- Typography: UI, heading and monospace font stacks, type sizes, weights and line heights.
- Spacing: a common 4px-based scale.
- Geometry: control heights, radii and icon-button size.
- Motion and stacking: transition durations and z-index levels.
- Semantic surfaces and feedback: application foreground/background, input and panel surfaces, placeholders, danger, success, warning and informational colors.
- Existing brand, role, button and message tokens.

The dark theme overrides semantic variables under `:root[data-theme="dark-soft"]`. Components do not need to change when adding another theme; values can be supplied through semantic CSS variables.

## Current source measurements

| File group | Lines | Characters |
|---|---:|---:|
| Theme tokens | 193 | 5,671 |
| Ordered style modules | 693 | 148,548 |
| **Total** | **886** | **154,219** |

Current style inventory:
- 39 media-query blocks.
- 626 `!important` declarations remain.
- 186 selector groups appear more than once across the ordered modules. Some are responsive/theme variants; others are legacy refinements and need component-by-component cascade review.
- 1,205 parsed CSS rule blocks.
- No unresolved CSS custom-property references.
- All 14 imported style modules were checked for balanced CSS blocks after extraction.

The stylesheet is now organized into focused modules, but all historical cascade complexity has not yet been removed. Further removal of important declarations and repeated selectors requires component-by-component visual regression checks because specificity, source order, media conditions and theme variants interact.

## Maintenance rules

1. Use an existing primitive and design token before adding a new local implementation.
2. Add shared behavior to the appropriate component; keep feature content and business logic in its feature module.
3. Edit the existing rule in its owning style module rather than appending a corrective override to the last file.
4. Preserve the documented import order until a cascade-aware migration deliberately changes it.
5. Keep mobile and desktop composition rules shared where behavior is shared; do not add a breakpoint-only copy merely to fix one component.
6. Check `min-width: 0`, overflow behavior, wrapping and text truncation for flex/grid children.
7. Require a production build and automated design-token check for CSS or component changes. Structural layout changes still require visual verification at mobile and desktop widths.
