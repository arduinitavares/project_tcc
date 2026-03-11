## 2026-03-06 - Missing aria-label on icon-only buttons
**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.
**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2026-03-06 - Stepper Accessibility Roles
**Learning:** This app uses `div` elements structured as multi-step components (steppers). These lack native semantic meaning for screen readers.
**Action:** When implementing or updating multi-step components built with `div`s, ensure the container has `role="list"` with an `aria-label`, each step has `role="listitem"`, and the active phase dynamically receives `aria-current="step"`.