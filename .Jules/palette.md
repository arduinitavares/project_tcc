## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2023-10-24 - Accessibility for div-based steppers
**Learning:** Found that multi-step components (steppers) built using `div`s lack native semantic meaning. Screen readers don't understand that these elements represent a sequential list of steps without explicit ARIA roles and state attributes.
**Action:** When implementing or updating div-based steppers, always apply `role="list"` with an `aria-label` to the container, `role="listitem"` to each step, and dynamically set `aria-current="step"` on the active phase via JavaScript.

## 2026-03-28 - Missing required indicators on forms
**Learning:** Found that required form fields (like project name and spec path) lacked semantic `required` attributes and visual indicators. This creates friction for users when they try to submit incomplete forms without prior warning. Also found that `required` attributes should NOT be applied to `readonly` inputs.
**Action:** When creating or updating HTML forms, ensure required fields have a visual indicator (e.g., `<span class="text-red-500">*</span>`) within the associated `<label>`. Also apply the semantic `required` attribute to the `<input>`, unless the input is marked `readonly` or `disabled`.
