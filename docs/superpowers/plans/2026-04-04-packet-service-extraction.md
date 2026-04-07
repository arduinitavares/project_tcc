# Packet Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move story/task packet endpoint orchestration out of `api.py` and into a dedicated `services/packets/packet_service.py` module.

**Architecture:** Keep the lower-level packet builders in `api.py` for now, but introduce a real packet service boundary for endpoint-level decisions and payload assembly. This keeps the slice incremental while aligning with the longer-term target of `services/packets/*`.

**Tech Stack:** FastAPI, pytest, TestClient, SQLModel

---

### Task 1: Add Red Tests For Packet Service Functions

**Files:**
- Add: `tests/test_packet_service.py`
- Test: `tests/test_packet_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_get_task_packet_returns_payload_without_render():
    ...


def test_get_task_packet_adds_render_when_flavor_is_requested():
    ...


def test_get_story_packet_raises_not_found_when_packet_missing():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packet_service.py -q`
Expected: FAIL with missing `services.packets.packet_service`.


### Task 2: Implement Packet Service Functions

**Files:**
- Add: `services/packets/__init__.py`
- Add: `services/packets/packet_service.py`
- Test: `tests/test_packet_service.py`

- [ ] **Step 1: Add `PacketServiceError` plus public story/task packet helpers**

Implement:
- `get_task_packet(...)`
- `get_story_packet(...)`

They should own:
- packet-not-found branching
- response payload assembly
- optional flavor rendering

- [ ] **Step 2: Run service tests**

Run: `uv run pytest tests/test_packet_service.py -q`
Expected: PASS


### Task 3: Delegate Packet Handlers In `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_flow.py`

- [ ] **Step 1: Update packet handlers**

Keep in `api.py`:
- product existence check
- session factory
- DB-scoped packet builder callbacks

Move into service:
- packet missing decision
- payload assembly and optional render injection

- [ ] **Step 2: Run regression tests**

Run:

```bash
uv run pytest \
  tests/test_packet_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py -k "packet" -q
```

Then run:

```bash
uv run pytest \
  tests/test_sprint_phase_service.py \
  tests/test_packet_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py -q
```

Expected: PASS
