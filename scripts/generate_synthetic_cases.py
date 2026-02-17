#!/usr/bin/env python3
"""
Generate Synthetic Hard Negative Benchmark Cases.
Derives new failure cases from existing passing cases by injecting specific faults.
Targets: p7, p9, p10.
"""
import json
import random
import argparse
from pathlib import Path
from typing import List, Dict, Any

# Add repo root to path
import sys
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

# Configuration for mutations
MUTATIONS = {
    "FORBIDDEN_CAPABILITY": [
        "The system shall provide real-time collaboration features.",
        "Users can access the public API for integration.",
        "The platform supports cryptocurrency payments.",
        "Include a cloud dashboard for remote management.",
        "Enable voice assistant integration."
    ],
    "REQUIRED_FIELD_MISSING": [
        # Strategy: Wipe the Acceptance Criteria
        "WIPE_AC"
    ],
    "SCOPE_CREEP": [
        "As a user, I want to manage physical inventory in the warehouse.",
        "As a driver, I want to optimize shipping routes.",
        "As a user, I want to stream video from my security cameras.",
        "As a user, I want to auction my items to the highest bidder."
    ],
    "CONTRADICTION": [
        "The story points for this task are 100.", # Violates MAX_VALUE
        "Latency must be under 0ms (impossible).",
        "The system must work offline but requires cloud sync."
    ]
}

def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases = []
    with open(path, 'r') as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases

def mutate_case(case: Dict[str, Any], mutation_type: str, mutation_payload: str) -> Dict[str, Any]:
    new_case = case.copy()
    # Generate new ID
    new_case["case_id"] = f"syn-{case.get('case_id', 'nocase')}-{mutation_type[:3]}"
    new_case["tags"] = ["synthetic", mutation_type]
    new_case["expected_pass"] = False
    new_case["label_source"] = "synthetic_mutation"
    new_case["enabled"] = True
    new_case["expected_fail_reasons"] = [] # Reset

    # Apply Mutation
    if mutation_type == "FORBIDDEN_CAPABILITY":
        new_case["story_description"] = (new_case.get("story_description", "") + " " + mutation_payload).strip()
        new_case["expected_fail_reasons"] = ["FORBIDDEN_CAPABILITY"]

    elif mutation_type == "REQUIRED_FIELD_MISSING":
        if mutation_payload == "WIPE_AC":
            new_case["acceptance_criteria"] = "" # Empty AC
            new_case["expected_fail_reasons"] = ["RULE_ACCEPTANCE_CRITERIA_REQUIRED"]

    elif mutation_type == "SCOPE_CREEP":
        new_case["story_title"] = mutation_payload
        new_case["story_description"] = "Out of scope feature request."
        new_case["expected_fail_reasons"] = ["LLM_SPEC_VALIDATION"]

    elif mutation_type == "CONTRADICTION":
        new_case["acceptance_criteria"] = (new_case.get("acceptance_criteria", "") + "\n" + mutation_payload).strip()
        new_case["expected_fail_reasons"] = ["MAX_VALUE"] if "points" in mutation_payload else ["LLM_SPEC_VALIDATION"]

    return new_case

def generate_synthetic_cases(source_cases: List[Dict[str, Any]], count: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    # Filter for passing cases to mutate (from cases_for_labeling, we check rater_pass or expected_pass)
    passing_cases = [c for c in source_cases if c.get("rater_pass") is True or c.get("expected_pass") is True]

    if not passing_cases:
        print("No passing cases found to mutate. Using all cases.")
        passing_cases = source_cases

    generated_cases = [] # For cases.jsonl format
    synthetic_stories = [] # For DB hydration

    print(f"Found {len(passing_cases)} source cases.")

    # P7 Mutations
    for i in range(count):
        source = random.choice(passing_cases)
        m_type = random.choice(list(MUTATIONS.keys()))
        m_payload = random.choice(MUTATIONS[m_type])

        syn_data = mutate_case(source, m_type, m_payload)
        syn_id = 7000 + i # Synthetic Story IDs
        prod_id = source.get("product_id", 7)

        syn_case_record = {
            "case_id": f"p7-syn-{i}",
            "story_id": syn_id,
            "spec_version_id": source["spec_version_id"],
            "expected_pass": False,
            "expected_fail_reasons": syn_data["expected_fail_reasons"],
            "notes": f"Mutation: {m_type}",
            "tags": ["synthetic", m_type],
            "enabled": True,
            "product_id": prod_id,
            "story_title": syn_data["story_title"],
            "spec_source": "synthetic",
            "label_source": "synthetic"
        }

        syn_story_record = {
            "story_id": syn_id,
            "product_id": prod_id,
            "title": syn_data["story_title"],
            "description": syn_data.get("story_description", ""),
            "acceptance_criteria": syn_data.get("acceptance_criteria", "")
        }

        generated_cases.append(syn_case_record)
        synthetic_stories.append(syn_story_record)

    # P9/P10 Setup
    p9_base = {
        "product_id": 9, "spec_version_id": 901,
        "story_title": "Add item to cart", "story_description": "As a user I want to add items.",
        "acceptance_criteria": "Given item, When add, Then in cart.", "rater_pass": True
    }

    p10_base = {
        "product_id": 10, "spec_version_id": 1001,
        "story_title": "Turn on light", "story_description": "As a user I want to turn on lights.",
        "acceptance_criteria": "Given light off, When toggle, Then on.", "rater_pass": True
    }

    # Generate P9 Failures
    for i in range(5):
        m_type = random.choice(list(MUTATIONS.keys()))
        m_payload = random.choice(MUTATIONS[m_type])
        syn_data = mutate_case(p9_base, m_type, m_payload)
        syn_id = 9000 + i

        syn_case_record = {
            "case_id": f"p9-syn-{i}",
            "story_id": syn_id,
            "spec_version_id": 901,
            "expected_pass": False,
            "expected_fail_reasons": syn_data["expected_fail_reasons"],
            "notes": f"Mutation: {m_type}",
            "tags": ["synthetic", m_type],
            "enabled": True,
            "product_id": 9,
            "story_title": syn_data["story_title"],
            "spec_source": "synthetic",
            "label_source": "synthetic"
        }
        syn_story_record = {
            "story_id": syn_id,
            "product_id": 9,
            "title": syn_data["story_title"],
            "description": syn_data.get("story_description", ""),
            "acceptance_criteria": syn_data.get("acceptance_criteria", "")
        }
        generated_cases.append(syn_case_record)
        synthetic_stories.append(syn_story_record)

    # Generate P10 Failures
    for i in range(5):
        m_type = random.choice(list(MUTATIONS.keys()))
        m_payload = random.choice(MUTATIONS[m_type])
        syn_data = mutate_case(p10_base, m_type, m_payload)
        syn_id = 10000 + i

        syn_case_record = {
            "case_id": f"p10-syn-{i}",
            "story_id": syn_id,
            "spec_version_id": 1001,
            "expected_pass": False,
            "expected_fail_reasons": syn_data["expected_fail_reasons"],
            "notes": f"Mutation: {m_type}",
            "tags": ["synthetic", m_type],
            "enabled": True,
            "product_id": 10,
            "story_title": syn_data["story_title"],
            "spec_source": "synthetic",
            "label_source": "synthetic"
        }
        syn_story_record = {
            "story_id": syn_id,
            "product_id": 10,
            "title": syn_data["story_title"],
            "description": syn_data.get("story_description", ""),
            "acceptance_criteria": syn_data.get("acceptance_criteria", "")
        }
        generated_cases.append(syn_case_record)
        synthetic_stories.append(syn_story_record)

    return generated_cases, synthetic_stories

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default="artifacts/validation_benchmark/cases_for_labeling.jsonl")
    parser.add_argument("--output-cases", type=Path, default="artifacts/validation_benchmark/cases.expanded.jsonl")
    parser.add_argument("--output-stories", type=Path, default="artifacts/validation_benchmark/synthetic_stories.jsonl")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    source_cases = load_cases(args.input)
    synthetic_cases, synthetic_stories = generate_synthetic_cases(source_cases, args.count)

    final_cases = []
    source_story_records = []

    for sc in source_cases:
        pass_val = sc.get("rater_pass")
        fail_reasons = sc.get("rater_fail_reasons", "")
        if isinstance(fail_reasons, str):
            fail_reasons = [r.strip() for r in fail_reasons.split(",") if r.strip()]

        final_cases.append({
            "case_id": sc["case_id"],
            "story_id": sc["story_id"],
            "spec_version_id": sc["spec_version_id"],
            "expected_pass": pass_val,
            "expected_fail_reasons": fail_reasons,
            "notes": sc.get("rater_notes"),
            "tags": ["real-data"],
            "enabled": True,
            "product_id": sc.get("product_id", 7),
            "story_title": sc["story_title"],
            "spec_source": "real",
            "label_source": "human_review"
        })

        source_story_records.append({
            "story_id": sc["story_id"],
            "product_id": sc.get("product_id", 7),
            "title": sc["story_title"],
            "description": sc.get("story_description", ""),
            "acceptance_criteria": sc.get("acceptance_criteria", "")
        })

    final_cases.extend(synthetic_cases)
    final_story_records = source_story_records + synthetic_stories

    # Add base P9/P10 passing cases
    final_cases.append({
        "case_id": "p9-base", "story_id": 9001, "spec_version_id": 901, "expected_pass": True, "product_id": 9, "story_title": "Base P9", "expected_fail_reasons": [], "tags": ["synthetic-base"], "enabled": True, "spec_source": "synthetic", "label_source": "synthetic"
    })
    final_story_records.append({"story_id": 9001, "product_id": 9, "title": "Base P9", "description": "As a user I want to add items.", "acceptance_criteria": "Given item, When add, Then in cart."})

    final_cases.append({
        "case_id": "p10-base", "story_id": 10001, "spec_version_id": 1001, "expected_pass": True, "product_id": 10, "story_title": "Base P10", "expected_fail_reasons": [], "tags": ["synthetic-base"], "enabled": True, "spec_source": "synthetic", "label_source": "synthetic"
    })
    final_story_records.append({"story_id": 10001, "product_id": 10, "title": "Base P10", "description": "As a user I want to turn on lights.", "acceptance_criteria": "Given light off, When toggle, Then on."})

    with open(args.output_cases, 'w') as f:
        for c in final_cases:
            f.write(json.dumps(c) + "\n")

    with open(args.output_stories, 'w') as f:
        for s in final_story_records:
            f.write(json.dumps(s) + "\n")

    print(f"Generated {len(synthetic_cases)} synthetic cases.")
    print(f"Total benchmark size: {len(final_cases)}")
    print(f"Total stories to hydrate: {len(final_story_records)}")

if __name__ == "__main__":
    main()
