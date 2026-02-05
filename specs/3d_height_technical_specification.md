# Technical Specification: 3D TIFF Analyzer CLI Tool

## 1. Project Overview

### 1.1 Purpose
Create an independent Python CLI tool that scans a folder tree for **3D depth TIFF images**, analyzes them using a defined 3D segmentation/statistics algorithm, and exports results to an **append-only CSV**. Optionally generates **annotated PNGs** for failures and/or outliers based on YAML-configured rules.

### 1.2 Target Root (default use)
`C:\Users\Yazzoom\Documents\codebase\log_images`

Folder structure contains date subfolders named `images_YYYY-MM-DD`, each containing mixed 2D and 3D TIFFs.

---

## 2. Inputs

### 2.1 File Discovery Rules
Process files under `--root` recursively, **ONLY** if all are true:

- Extension is `.tif` or `.tiff`
- Filename contains `3Dcamera_` (case-insensitive)
- Filename does **not** contain `annotated` (case-insensitive)
- Must ignore any `2Dcamera_*` files (even if TIFF)

### 2.2 Modes
Two execution modes:

1. **Batch mode**: analyze all eligible 3D TIFFs found under `--root` and write to CSV.
2. **Watch mode**: poll the filesystem repeatedly (default every 5 seconds), analyze only **newly appearing** eligible 3D TIFFs, and append results to the same CSV.

---

## 3. CLI Interface

### 3.1 Required / Supported Flags
- `--root <path>`: root directory to scan recursively
- `--rules <path>`: YAML rules file (required)
- `--csv <path>`: output CSV path (required)
- `--mode batch|watch`: run mode (required)
- `--poll-seconds <float>`: polling interval for watch mode (default e.g. `5`)
- `--algo-config <path>`: optional config for analyzer parameters (if separate from rules)

### 3.2 Behavior Requirements
- Tool must run **independently**: no imports from `support.read_configuration` or other project modules.
- Prefer **single script** unless multiple files are clearly necessary.
- Deterministic behavior (given same inputs/configs).
- PEP8 + type hints.
- No broad `except Exception:` usage; handle expected failures explicitly.

---

## 4. Outputs

## 4.1 CSV Output (Append-only)

### 4.1.1 General Requirements
- One row per analyzed 3D image.
- Append-only: never rewrite previous results.
- Must write a **stable header** (same columns every run).
- In watch mode, must resume from an existing CSV by:
  - Reading already processed `image_path` values
  - Reconstructing prior `height_mm` history for spike detection

### 4.1.2 Mandatory Base Fields (always present)
- `timestamp_utc` (UTC ISO-8601 string)
- `image_path` (full path)
- `image_name` (filename)
- `parent_folder` (folder containing the file; likely date folder)
- `success` (bool)
- `status` (string; short reason/message such as `ok`, `read_error`, `no_valid_pixels`, `no_components`, etc.)
- `is_outlier` (bool)
- `modified_z` (float; NaN/empty allowed if cannot compute)
- `annotated_path` (string path to annotated png if created else empty)

### 4.1.3 Measurement Fields (stable, explicit, no duplicates)
Include **all** measurement fields produced by the analyzer. At minimum include:

Global / union stats:
- `baseline` (float; depth units)
- `area_px` (int; union/object/primary area per defined schema)
- `depth_mean`, `depth_median`, `depth_p95` (float; depth units)

Bounding box fields (explicit names, stable):
- `bbox_x0`, `bbox_y0`, `bbox_x1`, `bbox_y1`, `bbox_w`, `bbox_h` (ints)

Left/mid/right region stats (within union bbox):
- `left_mean`, `left_p95`
- `mid_mean`, `mid_p95`
- `right_mean`, `right_p95`

Object/component stats:
- `object_count` (int; number of connected components retained)

Height fields (avoid duplication):
- `height` = raw height in depth units (`max_depth - baseline`)
- `height_mm` = converted millimeters

Any additional computed statistics must also be added as explicit columns, but the schema must remain stable across runs (see §4.1.4).

### 4.1.4 Stable Schema Rule
To keep the schema stable:
- Define an explicit ordered column list in code.
- If analyzer can compute optional fields, they must still appear as columns (empty/NaN if unavailable).
- Never emit duplicate semantic columns (example: do not write `height` twice). Use `height` and `height_mm` only.

---

## 4.2 Annotated Image Output (Conditional)

### 4.2.1 When to Save
Write annotated PNGs only when:
- Analysis fails **AND** `rules.annotate.on_fail == true`, OR
- `is_outlier == true` **OR** `rules.annotate.on_outlier == true`
- Optional override: `rules.annotate.all == true` forces annotation always

### 4.2.2 Output Location and Naming
- Save next to source TIFF
- Filename: `<stem>_annotated.png` (same directory as source)

### 4.2.3 Annotation Style: “Full Annotation”
Annotated PNG must include:
- TURBO colormap depth background
- Contours for **each** detected component (“per-cookie contours”)
- Bounding box for each component
- Per-component label text with:
  - index `#i`
  - `height_mm`
  - `area_px`
  - `depth_p95`
- A status header box (overall status, outlier flag, etc.)

Note: Components must be kept for annotation even if some are filtered for global stats (see §7.6 for definition).

---

## 5. Rules / Configuration (YAML)

### 5.1 Rule Loading
- Rules must be loaded from YAML, editable without code changes.
- **All configuration parameters must be configurable and must not be hard-coded in the script**, including (but not limited to):
  - analyzer thresholds (e.g., `min_depth_delta`)
  - invalid pixel value (`invalid_value`)
  - `border_frac`
  - morphology open/close kernel sizes
  - `min_component_area`
  - any mm conversion factor(s)
  - any percentile definitions (e.g., p95)
  - any segmentation connectivity settings
- Defaults are allowed, but they must be centralized in a configuration schema and overrideable via YAML and/or `--algo-config`.

### 5.2 Required Rule Keys
#### Height bounds (millimeters)
- `height_mm.min` (float)
- `height_mm.max` (float)

#### Spike detection
- `spike.window` (int) — rolling window size over prior heights (mm)
- `spike.modified_z_thresh` (float) — threshold for robust modified z-score

#### Annotation policy
- `annotate.on_fail` (bool)
- `annotate.on_outlier` (bool)
- `annotate.all` (bool, optional)

### 5.3 Units Requirement
All bounds and spike history are interpreted in **millimeters** (`height_mm`). Ensure conversion is applied consistently.

---

## 6. Outlier Definition

An image is an outlier if **any** of the following is true:

1. **Height spike**: robust modified z-score computed over rolling window of **prior** `height_mm` exceeds threshold:
   - `abs(modified_z) >= spike.modified_z_thresh`
2. **Out of bounds**:
   - `height_mm < height_mm.min` OR `height_mm > height_mm.max`

CSV must store:
- `is_outlier` (bool)
- `modified_z` (float)

If modified z-score cannot be computed (insufficient history), still evaluate bounds; set `modified_z` empty/NaN.

---

## 7. 3D Analysis Algorithm (Simple3DAnalyzer)

### 7.1 Loading and Normalization
- Load 3D TIFF into a numpy array as `float32`.
- If source data is `uint16`, normalize to `[0, 1]` by dividing by `2**16`.
- Define valid pixels: `depth > invalid_value` (invalid_value configurable; exact default must be defined in config).

### 7.2 Baseline Estimation
- Compute baseline as median of border pixels with configurable `border_frac`:
  - Border region is a frame around the image edges sized by `border_frac` of width/height.
- Use only valid pixels.
- If insufficient valid border pixels, fallback to median of all valid pixels.

### 7.3 Segmentation
- Threshold objects as: `depth > baseline + min_depth_delta`.
- Apply morphology open/close with configurable kernel sizes.

### 7.4 Connected Components
- Extract connected components with area >= `min_component_area`.
- Requirement: **keep all extracted components for annotation**.

### 7.5 Per-component Measurements
For each component:
- bbox (x0,y0,x1,y1,w,h)
- area_px
- height (raw depth units): `max(depth_in_component) - baseline`
- depth_p95 (percentile 95 of depth values in component)
- contour points (for drawing)

### 7.6 Global / Union Measurements
Compute union/global stats and left/mid/right column stats **within union bbox**:
- union bbox: bounding rectangle covering all components kept for global stats
- depth stats: mean/median/p95 of union mask values
- left/mid/right: compute within union bbox divided into three equal vertical regions
  - `left_*`, `mid_*`, `right_*` stats include mean and p95

(If no components, analysis fails with `success=false`, status indicates reason.)

---

## 8. Watch Mode State / Resuming

### 8.1 Previously Processed Images
When `--mode watch` starts:
- If CSV exists, read it and build a set of processed `image_path`
- Skip any matching paths found during scanning

### 8.2 Rebuilding Spike History
Also from CSV:
- Load prior `height_mm` values (only successful rows with numeric `height_mm` unless specified otherwise)
- Use these as the rolling history for modified z-score computation

### 8.3 Polling
- Scan recursively every `--poll-seconds`
- Process only newly discovered eligible 3D TIFFs

---

## 9. Error Handling and Status Codes

### 9.1 success/status
Each row must have `success` and `status`.
Examples of status values (must be stable and documented):
- `ok`
- `read_error`
- `invalid_shape`
- `no_valid_pixels`
- `baseline_failed`
- `no_components`
- `config_error`

On failure, measurement fields should be empty/NaN but columns must exist.

---

## 10. Non-Functional Requirements

- Single-script preferred.
- No external project dependencies.
- Deterministic processing order (e.g., sort file paths).
- Type hints across public functions.
- PEP8 compliance.

---

## 11. Testing Requirements (Unit Tests)

### 11.1 Test Framework
- Provide unit tests (recommended: `pytest`) to validate core behavior.

### 11.2 Minimum Unit Test Coverage
1. **Discovery filtering**
   - Accepts `3Dcamera_*.tif/.tiff` (case-insensitive)
   - Rejects files containing `annotated`
   - Rejects `2Dcamera_*` files
2. **CSV schema stability**
   - Header matches expected ordered column list
   - No duplicate columns
   - `height` and `height_mm` both present and distinct
3. **Batch mode**
   - Processes all eligible images and writes one row per image
4. **Watch resume behavior**
   - Reads existing CSV, skips already processed `image_path`
   - Reconstructs `height_mm` history for spike detection
5. **Outlier logic**
   - Bounds-based outliers
   - Modified z-score outliers using rolling window history
6. **Analyzer math invariants**
   - Baseline computed as border median with fallback
   - Segmentation threshold uses `baseline + min_depth_delta`
   - Connected components filtered by `min_component_area`
7. **Annotation policy decisions**
   - Annotates on failure when configured
   - Annotates on outlier when configured
   - Annotates always when `annotate.all=true`
8. **Deterministic outputs**
   - For a fixed synthetic input image and config, measurements are reproducible

### 11.3 Test Data Strategy
- Use synthetic numpy arrays and temporary files (tmp_path fixtures) to create small deterministic TIFFs.
- Avoid dependence on the real filesystem tree for unit tests.

---

## 12. Acceptance Criteria (Testable)

1. **Discovery**: tool processes only `.tif/.tiff` files containing `3Dcamera_` (case-insensitive), excluding any containing `annotated`, ignoring `2Dcamera_*`.
2. **Batch**: scans entire `--root` recursively and writes one CSV row per eligible image.
3. **Watch**: polls every N seconds, processes only new eligible images, appends to CSV.
4. **Resume**: watch mode reads existing CSV and skips processed `image_path`; spike history is reconstructed from CSV.
5. **CSV schema**: stable header, includes base fields + required measurement fields, with no duplicates; `height` and `height_mm` are distinct.
6. **Outliers**: outlier if bounds violated OR modified z spike; outputs `is_outlier` and `modified_z`.
7. **Annotation policy**: annotated PNG generated only under policy; filename `<stem>_annotated.png` next to TIFF.
8. **Annotation style**: turbo colormap + contours + bbox + per-component labels (#i, height_mm, area_px, depth_p95) + status header box.
9. **Config non-hardcoding**: all analyzer and rules parameters are configurable via YAML/`--algo-config`; no “magic numbers” embedded in logic.
10. **Unit tests**: test suite runs and validates the behaviors in §11.
