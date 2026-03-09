## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2026-03-09 - Accessibility of custom multi-step components
**Learning:** Identified a common pattern where custom multi-step "stepper" components built with simple `div` containers lacked semantic structure. Screen readers could not identify the list structure or which step was currently active.
**Action:** Ensure multi-step component containers use `role="list"`, individual steps use `role="listitem"`, and the active step is dynamically marked using `aria-current="step"`. Decorative connecting elements should use `aria-hidden="true"`.
