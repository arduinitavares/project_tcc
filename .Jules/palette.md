## 2026-03-14 - Visual and semantic indicators for required form fields
**Learning:** Found that required form inputs in modals lacked both the semantic `required` HTML attribute and a visual indicator (like a red asterisk) for users. This causes accessibility issues for screen readers and confusion for sighted users until they attempt to submit.
**Action:** When creating or updating HTML forms, ensure required fields have both the semantic `required` attribute on the `<input>` and a visual indicator (e.g., `<span class="text-red-500">*</span>`) within the associated `<label>` to meet UX accessibility standards.

## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2023-10-24 - Accessibility for div-based steppers
**Learning:** Found that multi-step components (steppers) built using `div`s lack native semantic meaning. Screen readers don't understand that these elements represent a sequential list of steps without explicit ARIA roles and state attributes.
**Action:** When implementing or updating div-based steppers, always apply `role="list"` with an `aria-label` to the container, `role="listitem"` to each step, and dynamically set `aria-current="step"` on the active phase via JavaScript.
