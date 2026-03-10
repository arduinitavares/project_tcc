## 2026-03-06 - Missing aria-label on icon-only buttons\n**Learning:** Found that several icon-only interactive elements (like the close modal button and back to dashboard link) lacked `aria-label`s. This is a common pattern in this app's components, where Google Material Symbols are used standalone.\n**Action:** Add `aria-label`s to all icon-only buttons to ensure they are screen-reader accessible.

## 2026-03-10 - Missing required field indicators
**Learning:** Found that required form fields (like the Project Name and Specification File Path in the create project modal) lacked visual indicators and semantic `required` attributes, making it unclear to users what information is mandatory before submission.
**Action:** Add semantic `required` attributes to required `<input>` fields and visual indicators (e.g., `<span class="text-red-500">*</span>`) to their corresponding `<label>` elements to improve form accessibility and usability.
