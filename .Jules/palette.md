## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2026-03-07 - Accessibility for Multi-step Stepper Components
**Learning:** Progress indicators (steppers) inherently rely on visual cues (colors, icons) to denote active, completed, and future states. Screen readers miss this context if the container is just a series of `div`s.
**Action:** When building or maintaining multi-step flows, ensure the container has `role="list"` and an `aria-label`, each step has `role="listitem"`, and dynamically apply `aria-current="step"` to the currently active phase.
