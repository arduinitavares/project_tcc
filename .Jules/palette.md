## 2026-03-06 - Missing aria-label on icon-only buttons
**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.
**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2026-03-06 - Accessible Div-based Steppers
**Learning:** Multi-step components (steppers) in this app are built using `div` elements instead of semantic lists. This makes it difficult for screen reader users to understand the number of steps and the current active step.
**Action:** Always ensure custom `div`-based multi-step components have their container set to `role="list"` with an `aria-label`, each step set to `role="listitem"`, and the active step dynamically marked with `aria-current="step"`.
