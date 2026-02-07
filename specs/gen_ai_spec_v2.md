# Review-First Human-in-the-Loop Extraction Pipeline  
**Technical Specification (Final Draft with Inline Change Annotations)**

---

## 1. Objectives

This system is designed around a **review-first, human-in-the-loop pipeline** to achieve the following goals:

1. Leverage user review effort as part of normal product usage  
2. Deliver outputs that users trust and are satisfied with  

3. Capture user feedback, confirmations, and corrections as explicit labels  
   **[EDITED: feedback capture is now conditional on data usage eligibility]**  
   **→ subject to explicit user attestation that reviewed content is free of NDA
   or contractual usage restrictions**

4. Produce high-quality, auditable datasets for continuous model retraining  
   **[EDITED: training data generation is no longer implicit]**  
   **→ only from review sessions that have passed data usage eligibility verification**

The pipeline is **stage-gated**, with explicit review checkpoints and immutable revisioning.

---

## 2. Core Principles

> **Every pipeline stage must emit a reviewable artifact.**

> **[ADDED] Reviewed data MUST NOT be used for training unless explicit data usage
> attestation has been granted by the user.**

> **[ADDED] User interfaces MUST expose actionable review guidance rather than
> raw probabilistic confidence scores or schema-oriented labels.**

Each stage produces:
- Machine output (model result)
- Human review artifact (visual + structured)
- Review delta (what changed)
- Gold snapshot (post-review ground truth)
- Training export (model-ready data)

**[EDITED]** Human review is a first-class system feature.  
**[EDITED]** Training eligibility and retraining timing are conditional outcomes, not assumptions.

---

## 2.1 Data Usage Eligibility Gate (Mandatory)  
**[ADDED — NEW SECTION]**

Before any user confirmations, corrections, or review deltas may be persisted
together with captured document snapshots, the system MUST enforce a
**Data Usage Eligibility Gate**.

### Attestation Requirement  
**[ADDED]**

The review UI MUST present a mandatory checkbox with the following semantics:

- The user explicitly confirms that:
  - Reviewed documents, snapshots, and derived annotations are free of NDA,
    confidentiality, or contractual restrictions that prohibit reuse
    for model training or analytics.
- The checkbox is unchecked by default.
- Attestation applies per document or per review session.

### Attestation Outcomes  
**[ADDED]**

| Attestation State | System Behavior |
|------------------|----------------|
| Accepted | Full review pipeline continues, including snapshot retention and training exports |
| Declined / Not Provided | Workflow terminates after result delivery |
| Revoked | All downstream training exports are blocked |

### Hard Stop Rule  
**[ADDED]**

If attestation is not granted:
- User confirmations MUST NOT be stored together with document snapshots
- Gold snapshots MUST NOT be generated
- Training datasets MUST NOT be produced
- The workflow ends immediately after user-facing delivery

This rule is a hard system invariant and MUST NOT be bypassed.

---

## 3. Stage-Gated Review Workflow

### Global Precondition  
**[ADDED]**

All review checkpoints (A–D) require an approved **Data Usage Eligibility Gate**
in order to persist review deltas, gold snapshots, or training artifacts.

Without approval:
- Checkpoints may render outputs to the user
- Review actions, gold data, and training exports MUST NOT be persisted

---

### 3.1 Checkpoint A — Primitive Review  
*(Detection + OCR + Style Classification)*

#### Machine Outputs
- Symbol bounding boxes
- **[EDITED] Internal detection confidence (not exposed in user UI)**
- Tag type / style code predictions
- OCR text (raw + normalized)
- Model provenance metadata

#### Review UI Requirements  
**[EDITED]**

- Page image with overlayed primitives
- Color-coded review states instead of numeric confidence values
- Review state legend:
  - **Green** → no review required
  - **Orange** → review recommended
  - **Red** → review required
- Hover details MAY include:
  - bounding box geometry
  - detected symbol or class name
  - OCR text
- **[REMOVED] Display of raw confidence percentages**

#### Review State Derivation  
**[ADDED]**

Review states are derived internally from:
- Model confidence
- Validation rules
- Business heuristics
- Disagreement signals

Numeric confidence values MUST NOT be directly exposed in the UI.

#### Assisted Class Selection  
**[ADDED]**

When a user selects or changes a symbol type, class, or tag:

- Each option MUST include a **human-readable description**
- Visual examples or thumbnails SHOULD be shown where available
- The **model-recommended class MUST be pre-selected** by default
- Options SHOULD be filtered to contextually valid choices
- Internal schema identifiers MUST NOT be shown as primary labels

The system MUST guide correct selection without requiring prior taxonomy knowledge.

#### User Actions
- Add / delete primitive
- Move / resize bounding box
- Change primitive class / symbol type
- Edit OCR text
- Change tag_type / style code
- Explicitly waive validation warnings

#### Exit Criteria
- All blocking (Red) review items resolved or waived
- User approves **Checkpoint A**

#### Derived Artifact Regeneration  
**[ADDED]**

When a user adds, deletes, or edits a bounding box:

- The action is recorded as a review delta and applied to the gold state
- All derived artifacts for the checkpoint MUST be regenerated
- The user receives a **complete, corrected output file** with no manual rework

**[ADDED] Model Lifecycle Clarification**
- Full-page detection is NOT re-run automatically per edit
- Optional per-object inference MAY be executed for new objects
- Model retraining does NOT occur inline

**[ADDED] Training Lifecycle Rule**
- Corrections are accumulated as labeled data
- Retraining occurs asynchronously and in batches
- Model deployment is decoupled from review sessions

#### Outputs  
**[EDITED: outputs now conditional on attestation]**
- `primitives_v{n}.jsonl | parquet`
- `review_actions_v{n}.jsonl`
- `gold_primitives_v{n}.jsonl`

---

### 3.2 Checkpoint B — Graph Assembly Review  
*(Topology & Connectivity)*

#### Review UI Requirements  
**[EDITED]**
- Graph overlay with color-coded review states
- Node and edge types include short descriptions
- Invalid or contextually impossible connections are hidden or disabled
- Raw confidence values are not displayed

#### Outputs  
**[EDITED: outputs now conditional on attestation]**
- `graph_v{n}.json`
- `graph_review_actions_v{n}.jsonl`
- `gold_graph_v{n}.json`

---

### 3.3 Checkpoint C — DEXPI Canonicalization Review

#### Review UI Requirements  
**[EDITED]**
- Object types and attributes include descriptions and schema hints
- Validation errors are surfaced as actionable review states
- Users are not required to understand the full DEXPI schema

#### Outputs  
**[EDITED: outputs now conditional on attestation]**
- `dexpi_v{n}.xml | json`
- `dexpi_review_actions_v{n}.jsonl`

---

### 3.4 Checkpoint D — AAS Publishing Review

#### Review UI Requirements  
**[EDITED]**
- Metadata fields use human-readable labels
- Required vs optional fields are clearly indicated
- Readiness is shown via review states, not probabilities

#### Outputs  
**[EDITED: outputs now conditional on attestation]**
- `aas_v{n}.json | aasx`
- Consumer-ready export package

---

## 4. Review Action (Delta) Schema

All user feedback is stored as **event-sourced deltas**, never silent overwrites.

**[EDITED]** Review actions MUST NOT be persisted if data usage attestation
has not been approved.

---

## 5. Gold Dataset Generation

Each approved checkpoint MAY produce training-ready datasets.

**[EDITED: dataset generation is no longer unconditional]**

### Eligibility Rules  
**[ADDED]**
- `data_usage_attested = true`
- Attestation timestamp precedes checkpoint approval
- Attestation has not been revoked

If any condition fails, dataset generation MUST be skipped.

---

## 6. Active Learning & Review Prioritization

### Review Priority Scoring  
**[EDITED]**

Internal priority scoring is based on:
- Model confidence
- Validation rule violations
- Business importance
- Novel or rare classes
- Disagreement patterns

Priority scores drive **review state assignment**, not UI display.

---

## 7. User Experience & Transparency

### Review Clarity  
**[EDITED]**
- Users are guided by review states and assisted choices
- The UI minimizes cognitive load and decision ambiguity
- Users can complete reviews without external documentation

---

## 8. Versioning, Audit, and Provenance

Each checkpoint approval records:
- Document revision ID
- Input hash
- Model versions
- Configuration versions
- Data usage attestation metadata

State is event-sourced to ensure reproducibility and auditability.

---

## 9. Minimal MVP Definition

### MVP-1: Primitive Review Loop

**[EDITED]**
- Includes data usage eligibility gate
- Uses review states instead of confidence scores
- Provides assisted class selection
- Produces complete corrected outputs per review

---

## 10. Definition of Done (Per Checkpoint)

A checkpoint is complete when:
- Users can complete review without taxonomy documentation
- All required review states are resolved
- Gold snapshots are produced (if attested)
- Training exports are reproducible (if attested)
- Model provenance is recorded

---

**End of Specification**
