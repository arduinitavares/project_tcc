## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2023-10-24 - Accessibility for div-based steppers
**Learning:** Found that multi-step components (steppers) built using `div`s lack native semantic meaning. Screen readers don't understand that these elements represent a sequential list of steps without explicit ARIA roles and state attributes.
**Action:** When implementing or updating div-based steppers, always apply `role="list"` with an `aria-label` to the container, `role="listitem"` to each step, and dynamically set `aria-current="step"` on the active phase via JavaScript.

## 2025-02-12 - Missing required indicators on form fields
**Learning:** Found that critical form fields (like project name, file paths, team names, and dates) were missing clear visual and semantic indicators for being required. This causes friction as users may not realize a field is mandatory until submission fails.
**Action:** Always include both a semantic `required` attribute on the input and a visual indicator (like `<span class="text-red-500">*</span>`) in the corresponding label for all required form fields.
