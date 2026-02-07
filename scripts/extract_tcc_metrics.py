#!/usr/bin/env python3
"""
TCC Metrics Extraction Script

Extracts evaluation metrics from the project's SQLite database(s) for
Chapter 6 (Resultados) of the thesis. Produces reproducible, auditable outputs.

Usage:
    python scripts/extract_tcc_metrics.py <db_path>
    python scripts/extract_tcc_metrics.py agile_simple.db
    python scripts/extract_tcc_metrics.py db/spec_authority_dev.db

Outputs:
    - artifacts/metrics_summary.csv
    - artifacts/metrics_summary.json
    - artifacts/query_results/*.csv (one per query)
    - stdout: Markdown-ready summary

Author: TCC Evaluation Script
Date: 2026-02-01
"""

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ============================================================================
# Data Classes for Metrics
# ============================================================================

@dataclass
class ProductMetrics:
    """Metrics for a single product/project."""
    product_id: int
    product_name: str
    created_at: str
    
    # Story counts
    total_stories: int = 0
    stories_with_spec_version_id: int = 0
    stories_with_validation_evidence: int = 0
    stories_approved_first_pass: int = 0
    stories_refined: int = 0
    
    # Sprint metrics
    sprint_count: int = 0
    sprint_plan_drafts: int = 0
    sprint_plan_saves: int = 0
    
    # Workflow timing (from WorkflowEvent)
    total_sprint_planning_duration_sec: float = 0.0
    avg_sprint_planning_duration_sec: float = 0.0

    # Flow Efficiency & Execution (Dev Support Agent)
    avg_story_cycle_time_hours: float = 0.0
    stories_with_evidence_links: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    
    # Spec Authority metrics
    spec_versions_count: int = 0
    spec_versions_approved: int = 0
    compiled_authorities_count: int = 0
    spec_accepted_count: int = 0
    spec_rejected_count: int = 0


@dataclass
class SmokeRunMetrics:
    """Aggregated metrics from smoke_runs.jsonl."""
    total_runs: int = 0
    pipeline_ran_count: int = 0
    alignment_rejected_count: int = 0
    acceptance_blocked_count: int = 0
    contract_passed_count: int = 0
    
    # Timing aggregates (milliseconds)
    avg_total_ms: float = 0.0
    avg_compile_ms: float = 0.0
    avg_pipeline_ms: float = 0.0
    avg_validation_ms: float = 0.0
    
    # Spec version pinning
    spec_version_id_match_count: int = 0
    spec_version_id_mismatch_count: int = 0


@dataclass
class ExtractionResult:
    """Complete extraction result."""
    extraction_timestamp: str
    db_path: str
    db_filename: str
    commit_hash: Optional[str]
    
    # Schema info
    tables: list = field(default_factory=list)
    
    # Per-product metrics
    products: list = field(default_factory=list)
    
    # Smoke run metrics (if available)
    smoke_runs: Optional[SmokeRunMetrics] = None
    
    # Workflow events summary
    workflow_events_by_type: dict = field(default_factory=dict)
    
    # Task mapping notes
    task_mapping_notes: str = ""


# ============================================================================
# Database Extraction Functions
# ============================================================================

def get_git_commit_hash() -> Optional[str]:
    """Get current git commit hash, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_schema_summary(cursor: sqlite3.Cursor) -> list[dict]:
    """Extract schema summary for all tables."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = []
    
    for (table_name,) in cursor.fetchall():
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [
            {
                "name": col[1],
                "type": col[2],
                "notnull": bool(col[3]),
                "pk": bool(col[5])
            }
            for col in cursor.fetchall()
        ]
        
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        
        tables.append({
            "name": table_name,
            "columns": columns,
            "row_count": row_count
        })
    
    return tables


def extract_product_metrics(cursor: sqlite3.Cursor) -> list[ProductMetrics]:
    """Extract metrics for each product in the database."""
    products = []
    
    # Get all products
    cursor.execute("""
        SELECT product_id, name, created_at 
        FROM products 
        ORDER BY product_id
    """)
    product_rows = cursor.fetchall()
    
    for product_id, name, created_at in product_rows:
        metrics = ProductMetrics(
            product_id=product_id,
            product_name=name,
            created_at=str(created_at)
        )
        
        # Story counts
        cursor.execute("""
            SELECT COUNT(*) FROM user_stories WHERE product_id = ?
        """, (product_id,))
        metrics.total_stories = cursor.fetchone()[0]
        
        # Check if accepted_spec_version_id column exists
        cursor.execute("PRAGMA table_info(user_stories)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'accepted_spec_version_id' in columns:
            cursor.execute("""
                SELECT COUNT(*) FROM user_stories 
                WHERE product_id = ? AND accepted_spec_version_id IS NOT NULL
            """, (product_id,))
            metrics.stories_with_spec_version_id = cursor.fetchone()[0]
        
        if 'validation_evidence' in columns:
            cursor.execute("""
                SELECT COUNT(*) FROM user_stories 
                WHERE product_id = ? AND validation_evidence IS NOT NULL
            """, (product_id,))
            metrics.stories_with_validation_evidence = cursor.fetchone()[0]
        
        # Sprint counts
        cursor.execute("""
            SELECT COUNT(*) FROM sprints WHERE product_id = ?
        """, (product_id,))
        metrics.sprint_count = cursor.fetchone()[0]
        
        # Workflow events
        cursor.execute("""
            SELECT event_type, COUNT(*) 
            FROM workflow_events 
            WHERE product_id = ?
            GROUP BY event_type
        """, (product_id,))
        for event_type, count in cursor.fetchall():
            if event_type == 'SPRINT_PLAN_DRAFT':
                metrics.sprint_plan_drafts = count
            elif event_type == 'SPRINT_PLAN_SAVED':
                metrics.sprint_plan_saves = count
        
        # Sprint planning timing
        cursor.execute("""
            SELECT SUM(duration_seconds), AVG(duration_seconds)
            FROM workflow_events 
            WHERE product_id = ? AND event_type = 'SPRINT_PLAN_SAVED' AND duration_seconds IS NOT NULL
        """, (product_id,))
        result = cursor.fetchone()
        if result[0]:
            metrics.total_sprint_planning_duration_sec = round(result[0], 2)
            metrics.avg_sprint_planning_duration_sec = round(result[1], 2)
        
        # Flow Efficiency (Cycle Time)
        if 'completed_at' in columns:
            cursor.execute("""
                SELECT AVG((julianday(completed_at) - julianday(created_at)) * 24)
                FROM user_stories
                WHERE product_id = ? AND completed_at IS NOT NULL AND created_at IS NOT NULL
            """, (product_id,))
            cycle_time = cursor.fetchone()[0]
            if cycle_time:
                metrics.avg_story_cycle_time_hours = round(cycle_time, 2)
        
        # Execution Evidence (DoD)
        if 'evidence_links' in columns:
            cursor.execute("""
                SELECT COUNT(*) FROM user_stories
                WHERE product_id = ? AND evidence_links IS NOT NULL AND evidence_links != '[]'
            """, (product_id,))
            metrics.stories_with_evidence_links = cursor.fetchone()[0]
            
        # Task Execution metrics (Dev Support Agent)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT COUNT(*), SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END)
                FROM tasks t
                JOIN user_stories us ON t.story_id = us.story_id
                WHERE us.product_id = ?
            """, (product_id,))
            task_res = cursor.fetchone()
            if task_res:
                metrics.total_tasks = task_res[0] or 0
                metrics.completed_tasks = task_res[1] or 0

        # Spec Authority metrics (if tables exist)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spec_registry'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT COUNT(*) FROM spec_registry WHERE product_id = ?
            """, (product_id,))
            metrics.spec_versions_count = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM spec_registry 
                WHERE product_id = ? AND status = 'approved'
            """, (product_id,))
            metrics.spec_versions_approved = cursor.fetchone()[0]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='compiled_spec_authority'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT COUNT(*) FROM compiled_spec_authority csa
                JOIN spec_registry sr ON csa.spec_version_id = sr.spec_version_id
                WHERE sr.product_id = ?
            """, (product_id,))
            metrics.compiled_authorities_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spec_authority_acceptance'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT status, COUNT(*) 
                FROM spec_authority_acceptance 
                WHERE product_id = ?
                GROUP BY status
            """, (product_id,))
            for status, count in cursor.fetchall():
                if status == 'accepted':
                    metrics.spec_accepted_count = count
                elif status == 'rejected':
                    metrics.spec_rejected_count = count
        
        products.append(metrics)
    
    return products


def extract_workflow_events_summary(cursor: sqlite3.Cursor) -> dict:
    """Extract summary of all workflow events."""
    cursor.execute("""
        SELECT event_type, COUNT(*), 
               AVG(duration_seconds), 
               SUM(duration_seconds),
               MIN(timestamp),
               MAX(timestamp)
        FROM workflow_events
        GROUP BY event_type
        ORDER BY event_type
    """)
    
    summary = {}
    for row in cursor.fetchall():
        event_type, count, avg_duration, total_duration, min_ts, max_ts = row
        summary[event_type] = {
            "count": count,
            "avg_duration_sec": round(avg_duration, 2) if avg_duration else None,
            "total_duration_sec": round(total_duration, 2) if total_duration else None,
            "first_event": min_ts,
            "last_event": max_ts
        }
    
    return summary


def extract_smoke_run_metrics(artifacts_dir: Path) -> Optional[SmokeRunMetrics]:
    """Extract metrics from smoke_runs.jsonl if available."""
    smoke_file = artifacts_dir / "smoke_runs.jsonl"
    if not smoke_file.exists():
        return None
    
    metrics = SmokeRunMetrics()
    total_ms_list = []
    compile_ms_list = []
    pipeline_ms_list = []
    validation_ms_list = []
    
    with open(smoke_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                run = json.loads(line)
                metrics.total_runs += 1
                
                # Stage counts
                stage = run.get("METRICS", {}).get("stage", "")
                if stage == "pipeline_ran":
                    metrics.pipeline_ran_count += 1
                elif stage == "alignment_rejected":
                    metrics.alignment_rejected_count += 1
                elif stage == "acceptance_blocked":
                    metrics.acceptance_blocked_count += 1
                
                # Contract passed
                if run.get("METRICS", {}).get("contract_passed") is True:
                    metrics.contract_passed_count += 1
                
                # Spec version ID match
                if run.get("SPEC_VERSION_ID_MATCH") is True:
                    metrics.spec_version_id_match_count += 1
                elif run.get("SPEC_VERSION_ID_MATCH") is False:
                    metrics.spec_version_id_mismatch_count += 1
                
                # Timing
                timing = run.get("TIMING_MS", {})
                if timing.get("total_ms") is not None:
                    total_ms_list.append(timing["total_ms"])
                if timing.get("compile_ms") is not None:
                    compile_ms_list.append(timing["compile_ms"])
                if timing.get("pipeline_ms") is not None:
                    pipeline_ms_list.append(timing["pipeline_ms"])
                if timing.get("validation_ms") is not None:
                    validation_ms_list.append(timing["validation_ms"])
                    
            except json.JSONDecodeError:
                continue
    
    # Calculate averages
    if total_ms_list:
        metrics.avg_total_ms = round(sum(total_ms_list) / len(total_ms_list), 2)
    if compile_ms_list:
        metrics.avg_compile_ms = round(sum(compile_ms_list) / len(compile_ms_list), 2)
    if pipeline_ms_list:
        metrics.avg_pipeline_ms = round(sum(pipeline_ms_list) / len(pipeline_ms_list), 2)
    if validation_ms_list:
        metrics.avg_validation_ms = round(sum(validation_ms_list) / len(validation_ms_list), 2)
    
    return metrics


# ============================================================================
# Task Mapping (T1-T5)
# ============================================================================

TASK_MAPPING_NOTES = """
## Task-to-Event Mapping (T1-T5)

The database does NOT encode T1-T5 directly. Proposed mapping:

| Task | Description | DB Representation | Notes |
|------|-------------|-------------------|-------|
| T1 | Definição de Visão | products.vision, products.created_at | No explicit timing event |
| T2 | Especificação Técnica | products.technical_spec, spec_registry | No explicit timing event |
| T3 | Compilação de Autoridade | compiled_spec_authority.compiled_at, spec_authority_acceptance | Timing available via compiled_at |
| T4 | Geração de Backlog | user_stories.created_at, validation_evidence | Aggregate by product |
| T5 | Planejamento de Sprint | WorkflowEvent.SPRINT_PLAN_SAVED.duration_seconds | Explicit timing available |

**Caveats:**
- T1/T2/T4 cycle times must be computed as wall-clock differences between timestamps
- Baseline manual times are NOT in the database (collected externally)
- NASA-TLX scores are NOT stored in the database (collected via questionnaire)

**Recommended approach:**
- Use WorkflowEvent timestamps for T5 (sprint planning) cycle time
- Use products.created_at and first story created_at for T4 rough estimate
- Use spec_registry/compiled_spec_authority timestamps for T3
- T1/T2 timing requires external baseline data or session logs
"""


# ============================================================================
# Output Functions
# ============================================================================

def write_csv_results(output_dir: Path, result: ExtractionResult):
    """Write per-query CSV files."""
    query_dir = output_dir / "query_results"
    query_dir.mkdir(parents=True, exist_ok=True)
    
    # Products summary
    if result.products:
        with open(query_dir / "products_metrics.csv", 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=asdict(result.products[0]).keys())
            writer.writeheader()
            for p in result.products:
                writer.writerow(asdict(p))
    
    # Workflow events
    if result.workflow_events_by_type:
        with open(query_dir / "workflow_events_summary.csv", 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["event_type", "count", "avg_duration_sec", "total_duration_sec", "first_event", "last_event"])
            for event_type, data in result.workflow_events_by_type.items():
                writer.writerow([
                    event_type,
                    data["count"],
                    data["avg_duration_sec"],
                    data["total_duration_sec"],
                    data["first_event"],
                    data["last_event"]
                ])
    
    # Smoke runs
    if result.smoke_runs:
        with open(query_dir / "smoke_runs_metrics.csv", 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=asdict(result.smoke_runs).keys())
            writer.writeheader()
            writer.writerow(asdict(result.smoke_runs))


def write_summary_csv(output_file: Path, result: ExtractionResult):
    """Write main metrics summary CSV."""
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header section
        writer.writerow(["=== EXTRACTION METADATA ==="])
        writer.writerow(["timestamp", result.extraction_timestamp])
        writer.writerow(["db_path", result.db_path])
        writer.writerow(["db_filename", result.db_filename])
        writer.writerow(["commit_hash", result.commit_hash or "N/A"])
        writer.writerow([])
        
        # Per-product metrics
        writer.writerow(["=== PRODUCT METRICS ==="])
        if result.products:
            headers = list(asdict(result.products[0]).keys())
            writer.writerow(headers)
            for p in result.products:
                writer.writerow(list(asdict(p).values()))
        writer.writerow([])
        
        # Workflow events
        writer.writerow(["=== WORKFLOW EVENTS ==="])
        writer.writerow(["event_type", "count", "avg_duration_sec", "total_duration_sec"])
        for event_type, data in result.workflow_events_by_type.items():
            writer.writerow([event_type, data["count"], data["avg_duration_sec"], data["total_duration_sec"]])


def write_summary_json(output_file: Path, result: ExtractionResult):
    """Write main metrics summary JSON."""
    output_dict = {
        "extraction_metadata": {
            "timestamp": result.extraction_timestamp,
            "db_path": result.db_path,
            "db_filename": result.db_filename,
            "commit_hash": result.commit_hash
        },
        "schema": {
            "tables": result.tables
        },
        "products": [asdict(p) for p in result.products],
        "workflow_events": result.workflow_events_by_type,
        "smoke_runs": asdict(result.smoke_runs) if result.smoke_runs else None,
        "task_mapping_notes": result.task_mapping_notes
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_dict, f, indent=2, ensure_ascii=False)


def print_markdown_summary(result: ExtractionResult):
    """Print markdown-ready summary to stdout."""
    print("=" * 80)
    print("# TCC Metrics Extraction Summary")
    print("=" * 80)
    print()
    print(f"**Database:** `{result.db_filename}`")
    print(f"**Extraction Time:** {result.extraction_timestamp}")
    print(f"**Commit Hash:** {result.commit_hash or 'N/A'}")
    print()
    
    # Products table
    print("## Products Summary")
    print()
    print("| Product ID | Name | Stories | w/ Spec Version | Sprints | Sprint Plan Events |")
    print("|------------|------|---------|-----------------|---------|-------------------|")
    for p in result.products:
        name_short = p.product_name[:40] + "..." if len(p.product_name) > 40 else p.product_name
        print(f"| {p.product_id} | {name_short} | {p.total_stories} | {p.stories_with_spec_version_id} | {p.sprint_count} | {p.sprint_plan_saves} |")
    print()
    
    # Workflow events
    print("## Workflow Events Summary")
    print()
    print("| Event Type | Count | Avg Duration (s) | Total Duration (s) |")
    print("|------------|-------|------------------|-------------------|")
    for event_type, data in result.workflow_events_by_type.items():
        avg_dur = data["avg_duration_sec"] if data["avg_duration_sec"] else "N/A"
        total_dur = data["total_duration_sec"] if data["total_duration_sec"] else "N/A"
        print(f"| {event_type} | {data['count']} | {avg_dur} | {total_dur} |")
    print()
    
    # Spec Authority Pinning Coverage
    print("## Spec Authority Pinning Coverage")
    print()
    total_stories = sum(p.total_stories for p in result.products)
    total_with_spec = sum(p.stories_with_spec_version_id for p in result.products)
    pct = (total_with_spec / total_stories * 100) if total_stories > 0 else 0
    print(f"- Total stories: {total_stories}")
    print(f"- Stories with valid `accepted_spec_version_id`: {total_with_spec} ({pct:.1f}%)")
    print(f"- Stories without spec version: {total_stories - total_with_spec}")
    print()

    # Flow Efficiency & Execution Metrics (Added for Proposal alignment)
    print("## Flow Efficiency & Execution Metrics")
    print()
    print("| Product | Avg Story Cycle Time (h) | Stories w/ Evidence | Tasks (Done/Total) |")
    print("|---------|--------------------------|---------------------|--------------------|")
    for p in result.products:
        name_short = p.product_name[:20] 
        task_info = f"{p.completed_tasks}/{p.total_tasks}"
        print(f"| {name_short} | {p.avg_story_cycle_time_hours} | {p.stories_with_evidence_links} | {task_info} |")
    print()
    
    # Smoke runs (if available)
    if result.smoke_runs:
        sr = result.smoke_runs
        print("## Smoke Run Metrics (from smoke_runs.jsonl)")
        print()
        print(f"- Total runs: {sr.total_runs}")
        print(f"- Pipeline ran: {sr.pipeline_ran_count}")
        print(f"- Alignment rejected: {sr.alignment_rejected_count}")
        print(f"- Acceptance blocked: {sr.acceptance_blocked_count}")
        print(f"- Contract passed: {sr.contract_passed_count}")
        print(f"- Spec version ID match: {sr.spec_version_id_match_count}")
        print()
        print("### Timing (avg ms)")
        print(f"- Total: {sr.avg_total_ms}")
        print(f"- Compile: {sr.avg_compile_ms}")
        print(f"- Pipeline: {sr.avg_pipeline_ms}")
        print(f"- Validation: {sr.avg_validation_ms}")
        print()
    
    # Task mapping
    print("## Task-to-Event Mapping (T1-T5)")
    print()
    print("| Task | DB Event/Table | Timing Available |")
    print("|------|----------------|------------------|")
    print("| T1 - Vision | products.vision | No (external) |")
    print("| T2 - Tech Spec | spec_registry | No (external) |")
    print("| T3 - Compile Authority | compiled_spec_authority | Yes (compiled_at) |")
    print("| T4 - Backlog Gen | user_stories | Partial (created_at) |")
    print("| T5 - Sprint Plan | WorkflowEvent.SPRINT_PLAN_SAVED | Yes (duration_seconds) |")
    print()
    print("**Note:** Baseline manual times and NASA-TLX scores are NOT in the database.")
    print("[PLACEHOLDER: Baseline timing data collected externally via stopwatch]")
    print("[PLACEHOLDER: NASA-TLX scores collected via self-assessment questionnaire]")
    print()
    
    # Sprint planning cycle time
    print("## Sprint Planning Cycle Time (T5)")
    print()
    print("| Product ID | Duration (s) | Interpretation |")
    print("|------------|--------------|----------------|")
    for p in result.products:
        if p.total_sprint_planning_duration_sec > 0:
            print(f"| {p.product_id} | {p.total_sprint_planning_duration_sec} | SPRINT_PLAN_SAVED.duration_seconds |")
    print()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract TCC evaluation metrics from SQLite database"
    )
    parser.add_argument(
        "db_path",
        help="Path to SQLite database file (e.g., agile_simple.db)"
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts",
        help="Output directory for extracted files (default: artifacts)"
    )
    args = parser.parse_args()
    
    # Resolve paths
    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        # Try relative to project root
        project_root = Path(__file__).parent.parent
        db_path = (project_root / args.db_path).resolve()
    
    if not db_path.exists():
        print(f"ERROR: Database file not found: {args.db_path}", file=sys.stderr)
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).parent.parent / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize result
    result = ExtractionResult(
        extraction_timestamp=datetime.now(timezone.utc).isoformat(),
        db_path=str(db_path),
        db_filename=db_path.name,
        commit_hash=get_git_commit_hash(),
        task_mapping_notes=TASK_MAPPING_NOTES
    )
    
    # Connect to database
    print(f"Connecting to database: {db_path}", file=sys.stderr)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Extract data
    print("Extracting schema summary...", file=sys.stderr)
    result.tables = get_schema_summary(cursor)
    
    print("Extracting product metrics...", file=sys.stderr)
    result.products = extract_product_metrics(cursor)
    
    print("Extracting workflow events...", file=sys.stderr)
    result.workflow_events_by_type = extract_workflow_events_summary(cursor)
    
    conn.close()
    
    # Extract smoke run metrics (from artifacts dir)
    artifacts_path = Path(__file__).parent.parent / "artifacts"
    print("Checking for smoke_runs.jsonl...", file=sys.stderr)
    result.smoke_runs = extract_smoke_run_metrics(artifacts_path)
    
    # Write outputs
    print(f"Writing outputs to {output_dir}/...", file=sys.stderr)
    write_summary_csv(output_dir / "metrics_summary.csv", result)
    write_summary_json(output_dir / "metrics_summary.json", result)
    write_csv_results(output_dir, result)
    
    # Print markdown summary to stdout
    print_markdown_summary(result)
    
    print(f"\nOutputs written to:", file=sys.stderr)
    print(f"  - {output_dir}/metrics_summary.csv", file=sys.stderr)
    print(f"  - {output_dir}/metrics_summary.json", file=sys.stderr)
    print(f"  - {output_dir}/query_results/*.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
