# Spec Authority PR Investigation Issues

Last updated: 2026-02-15
Branch reviewed: `impl-llm-spec-authority-extraction-5733517371646780942`
Commit reviewed: `34535aa`

## Open Issues

1. `validate_story_with_spec_authority` skips invariant alignment when alignment checker module is missing.
- Location: `tools/spec_tools.py:2204`, `tools/spec_tools.py:2237`
- Current behavior: import path `orchestrator_agent.agent_tools.story_pipeline.alignment_checker` is not present in this workspace; code catches `ImportError` and continues with only structural checks.
- Risk: stories can pass deterministic structural validation without being checked against compiled-authority invariants.
- Expected: alignment checker import resolves and runs, or validator fails closed when alignment module is unavailable.
- Status: Open

2. `compile_spec_authority` exception handling is narrower than robust compile path.
- Location: `tools/spec_tools.py:1123`
- Current behavior: catches only `ValueError` from `_extract_spec_authority_llm`.
- Risk: non-`ValueError` failures from compiler invocation/runtime can bubble up instead of returning a structured error payload.
- Expected: match defensive handling pattern used in `compile_spec_authority_for_version` (`tools/spec_tools.py:1306`).
- Status: Open

3. Inconsistent metadata behavior between compile paths.
- Location: `tools/spec_tools.py:1173`, `tools/spec_tools.py:1148`
- Current behavior:
  - `compile_spec_authority` returns truncated `prompt_hash` (`[:8]`).
  - Uses `SPEC_COMPILER_VERSION` constant.
- Risk: output differs from `compile_spec_authority_for_version`, which returns full hash and uses `SPEC_AUTHORITY_COMPILER_VERSION`.
- Status: Open

4. `compile_spec_authority` does not implement `content_ref` fallback when stored content is empty.
- Location: `tools/spec_tools.py:1125` (no fallback), compare with `tools/spec_tools.py:1274`.
- Risk: behavior mismatch; explicit compile can fail or compile with empty content in scenarios where robust path would load from file reference.
- Status: Open

5. Potential invariant ID collision in compiled authority artifact (project 7 sample).
- Evidence: multiple distinct invariants share same `id` values (example: `INV-346cc47f6a55c3d1` used for multiple `FORBIDDEN_CAPABILITY` rules; `INV-fd6a1efeb2f4d458` used for multiple `REQUIRED_FIELD` rules).
- Risk: downstream traceability and per-invariant diagnostics become ambiguous if IDs are not unique per invariant.
- Status: Open

6. Determinism expectation is only partially met in current runtime.
- Current intended design: deterministic gate using pinned `spec_version_id`, persisted `validation_evidence`, and invariant alignment findings.
- Current effective behavior in this workspace: deterministic structural checks run, but invariant alignment can be skipped due to issue #1.
- Clarification: backup module `C:\Users\mjnrc\projects\backup\story_pipeline\spec_validator_agent\agent.py` is LLM-based (`LlmAgent` + `LiteLlm`) with deterministic output schema, so semantic judgment there is not fully deterministic.
- Status: Open

## Validation Notes

- Test run in venv:
  - `python -m pytest -q tests/test_spec_authority.py` -> `18 passed`
  - `python -m pytest -q tests/test_spec_authority_compile_tool.py` -> `6 passed`
- Interpretation: current test suite passes, but does not fully guard against the issues above.

## Validation Flow Notes (Current)

1. Story validation entrypoint: `validate_story_with_spec_authority` in `tools/spec_tools.py:2059`.
2. Preconditions enforced: spec exists, product matches, compiled authority row exists.
3. Compiled artifact is loaded via `_load_compiled_artifact` for invariant audit context.
4. Alignment check is attempted through `validate_feature_alignment(...)`; currently skipped on `ImportError`.
5. Structural deterministic rules still run (title, acceptance criteria, persona-format warning).
6. `validation_evidence` is always persisted; `accepted_spec_version_id` is set only on pass.
