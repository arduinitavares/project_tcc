## 2024-05-24 - Workflow Stepper Accessibility

**Learning:** When implementing or updating multi-step components (steppers) built with `div`s, ensure the container has `role="list"` with an `aria-label`, each step has `role="listitem"`, and the active phase dynamically receives `aria-current="step"` for screen reader accessibility.

**Action:** Update the workflow stepper in `frontend/project.html` and `frontend/project.js` to dynamically apply these ARIA attributes based on the FSM state.