# Review-First Human-in-the-Loop Extraction Pipeline  
**Technical Specification (Draft)**

---

## 1. Objectives

This system is designed around a **review-first, human-in-the-loop pipeline** to achieve the following goals:

1. Leverage user review effort as part of normal product usage  
2. Deliver outputs that users trust and are satisfied with  
3. Capture user feedback, confirmations, and corrections as explicit labels  
4. Produce high-quality, auditable datasets for continuous model retraining  

The pipeline is **stage-gated**, with explicit review checkpoints and immutable revisioning.

---

## 2. Core Principle

> **Every pipeline stage must emit a reviewable artifact.**

Each stage produces:
- Machine output (model result)
- Human review artifact (visual + structured)
- Review delta (what changed)
- Gold snapshot (post-review ground truth)
- Training export (model-ready data)

Human review is not an exception path — it is a first-class system feature.

---

## 3. Stage-Gated Review Workflow

### 3.1 Checkpoint A — Primitive Review  
*(Detection + OCR + Style Classification)*

#### Machine Outputs
- Symbol bounding boxes
- Detection confidence
- Tag type / style code predictions
- OCR text (raw + normalized)
- Model provenance metadata

#### Review UI Requirements
- Page image with overlayed primitives
- Color-coded by confidence
- Hover details:
  - bbox coordinates
  - detection score
  - OCR text + confidence
  - tag_type + classification confidence

#### User Actions
- Add / delete primitive
- Move / resize bounding box
- Change primitive class / symbol type
- Edit OCR text
- Change tag_type / style code
- Explicitly waive validation warnings

#### Exit Criteria
- All blocking issues resolved or waived
- User approves **Checkpoint A**

#### Outputs
- `primitives_v{n}.jsonl | parquet`
- `review_actions_v{n}.jsonl`
- `gold_primitives_v{n}.jsonl`

---

### 3.2 Checkpoint B — Graph Assembly Review  
*(Topology & Connectivity)*

#### Machine Outputs
- Nodes (equipment, instruments, junctions)
- Edges (pipes, signals, flows)
- Confidence and evidence per edge

#### Review UI Requirements
- Graph overlay on drawing
- Node/edge list with validation warnings:
  - orphan nodes
  - impossible connections
  - disconnected components

#### User Actions
- Add / remove edges
- Fix edge direction
- Merge / split nodes
- Confirm or waive graph validation issues

#### Outputs
- `graph_v{n}.json`
- `graph_review_actions_v{n}.jsonl`
- `gold_graph_v{n}.json`

---

### 3.3 Checkpoint C — DEXPI Canonicalization Review

#### Machine Outputs
- DEXPI objects mapped from graph nodes
- Schema validation results
- Traceability links to graph primitives

#### User Actions
- Correct object types
- Fill missing attributes
- Fix mapping inconsistencies

#### Outputs
- `dexpi_v{n}.xml | json`
- `dexpi_review_actions_v{n}.jsonl`

---

### 3.4 Checkpoint D — AAS Publishing Review

#### Machine Outputs
- AAS submodels
- Required field checklist per consumer
- Validation status

#### User Actions
- Confirm or edit metadata
- Approve publishing

#### Outputs
- `aas_v{n}.json | aasx`
- Consumer-ready export package

---

## 4. Review Action (Delta) Schema

All user feedback is stored as **event-sourced deltas**, never silent overwrites.

### ReviewAction (Draft)

- `action_id`: UUID
- `doc_id`
- `page_id` (nullable for graph/DEXPI)
- `checkpoint`: `primitive | graph | dexpi | aas`
- `target_type`: `primitive | node | edge | text`
- `target_id` (or temp_id for new objects)
- `action_type`:
  - `create`
  - `delete`
  - `update_geometry`
  - `update_class`
  - `update_text`
  - `update_attribute`
  - `link`
  - `unlink`
  - `approve`
  - `waive_issue`
- `before`: JSON (optional, recommended)
- `after`: JSON
- `reason` (optional):
  - `low_confidence`
  - `schema_mismatch`
  - `user_found`
  - `cleanup`
- `reviewer_id`
- `timestamp`
- `model_provenance`

---

## 5. Gold Dataset Generation

Each approved checkpoint produces **training-ready datasets**.

### 5.1 Detection Dataset
- Image
- Bounding boxes
- Classes
- Ignored regions (optional)
- Source: `gold_primitives`

### 5.2 OCR Dataset
- Cropped image
- Raw text
- Normalized text
- Human-edited flag

### 5.3 Classification Dataset
- Cropped image
- tag_type / style_code labels
- Multi-label components (if applicable)

### 5.4 Association Dataset (future)
- Positive and negative symbol↔text links

---

## 6. Active Learning & Review Prioritization

### 6.1 Review Priority Scoring
Each item receives a `review_priority` based on:
- Low model confidence
- Business importance (e.g., tag regex match)
- Disagreement between sources
- Novel or rare class/style
- Validation rule violations

Only top-K items are **mandatory review**.

### 6.2 Auto-Acceptance
- Items above acceptance threshold auto-accepted
- Marked as `auto_accepted=true`
- Can be down-weighted during retraining

---

## 7. User Experience & Incentives

### 7.1 Review Load Control
- Mandatory vs optional review queues
- Bulk accept / bulk edit tools
- Regex-based correction suggestions

### 7.2 Transparency & Trust
- Per-page progress indicators
- Confidence heatmaps
- Clear indication of what will be retrained

### 7.3 Payback Loop
- Explicit messaging:
  - “Your corrections improve future results”
  - “This project legend will be reused”

---

## 8. Versioning, Audit, and Provenance

### 8.1 Immutable Revisions
Each checkpoint approval creates:
- `doc_revision_id`
- Input hash (PDF SHA-256)
- Model versions
- Config versions (DPI, thresholds, legend.yml)

### 8.2 Event-Sourced State
- Current state = replay(review_actions)
- Enables:
  - reproducibility
  - debugging
  - deterministic training exports

---

## 9. Minimal MVP Definition

### MVP-1: Primitive Review Loop
- Detection + classification only
- Review UI supports:
  - accept all
  - edit bbox
  - change tag_type
  - delete false positives
  - add missing primitive
- Outputs:
  - primitives
  - review deltas
  - gold dataset
- Training export:
  - COCO (detection)
  - cropped classification dataset

This MVP already satisfies the full **payback loop**.

---

## 10. Definition of Done (Per Checkpoint)

A checkpoint is complete when:
- User can review and correct outputs
- Corrections are stored as deltas
- Gold snapshot is produced
- Training export is reproducible
- Model provenance is recorded
- Validation issues are resolved or waived explicitly

---

**End of Specification**
