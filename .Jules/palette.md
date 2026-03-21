## 2026-03-06 - Missing aria-label on icon-only buttons
**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.
**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2023-10-24 - Accessibility for div-based steppers
**Learning:** Found that multi-step components (steppers) built using `div`s lack native semantic meaning. Screen readers don't understand that these elements represent a sequential list of steps without explicit ARIA roles and state attributes.
**Action:** When implementing or updating div-based steppers, always apply `role="list"` with an `aria-label` to the container, `role="listitem"` to each step, and dynamically set `aria-current="step"` on the active phase via JavaScript.

## 2024-03-21 - Visual and semantic required field indicators
**Learning:** Identified that mandatory fields in modals (e.g., "Create New Project") lacked explicit visual markers (`*`) and semantic HTML5 attributes (`required`), causing potential confusion regarding form completion requirements.
**Action:** Always include a visual indicator (`<span class="text-red-500">*</span>`) inside the `<label>` and apply the semantic `required` attribute to the associated `<input>` element for mandatory form fields.
