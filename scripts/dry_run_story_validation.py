#!/usr/bin/env python3
"""
Dry-run script to validate stories against spec authority without persisting changes.
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any
from sqlmodel import Session, select, create_engine, SQLModel
import json

# Add project root to path so we can import models/tools
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from agile_sqlmodel import UserStory, SpecRegistry, CompiledSpecAuthority
from utils.schemes import ValidationEvidence
from tools.spec_tools import validate_story_with_spec_authority, ValidateStoryInput

# Initialize engine relative to script execution
db_path = project_root / "db" / "spec_authority_dev.db"
# Use check_same_thread=False for sqlite compatibility scripts
engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

def dry_run_validation(product_id: int):
    print(f"Connecting to DB: {db_path}")
    
    with Session(engine) as session:
        # 1. Get the APPROVED spec version for this product
        statement = select(SpecRegistry).where(
            SpecRegistry.product_id == product_id,
            SpecRegistry.status == "approved"
        ).order_by(SpecRegistry.spec_version_id.desc())

        
        spec = session.exec(statement).first()
        
        if not spec:
            print(f"ERROR: No approved spec found for product {product_id}")
            return

        print(f"Using Spec Version {spec.spec_version_id} (ID: {spec.spec_version_id})")
        
        # 2. Get all stories for product
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()
        
        print(f"Found {len(stories)} stories to validate.")
        print("-" * 60)
        
        passed_count = 0
        failed_count = 0
        
        # 3. Simulate validation for each
        # CAUTION: validating modifies the DB session, so we must NOT commit.
        # tools.spec_tools creates a NEW session. Use caution.
        # Actually `validate_story_with_spec_authority` manages its own session/commit.
        # To make this a DRY RUN, we should ideally invoke the logic without the commit.
        # But since the tool is hardcoded to commit, we can't easily suppress it 
        # unless we monkeypatch Session.commit or reimplement the check.
        
        # PLAN B: Re-implement the check logic here to avoid side effects
        # Fetch compiled authority content
        compiled = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec.spec_version_id
            )
        ).first()
        
        if not compiled:
            print("ERROR: No compiled authority found for this spec version.")
            return
            
        authority = json.loads(compiled.compiled_artifact_json)
        invariants = authority.get("invariants", [])
        
        print(f"Loaded {len(invariants)} invariants from authority.")
        
        for story in stories:
            # Basic validation logic (simplified mirror of spec_tools)
            story_failures = []
            
            # Check 1: Required fields
            if not story.title:
                story_failures.append("Missing title")
            if not story.acceptance_criteria:
                story_failures.append("Missing acceptance_criteria")
                
            # Check 2: Invariants (simplified check)
            # Just checking forbidden terms as a sample
            for inv in invariants:
                if inv["type"] == "FORBIDDEN_CAPABILITY":
                    term = inv["parameters"].get("capability", "")
                    if term and term in (story.story_description or ""):
                        story_failures.append(f"Forbidden term found: {term}")
            
            # Result
            if not story_failures:
                status = "PASS"
                passed_count += 1
            else:
                status = "FAIL"
                failed_count += 1
                
            print(f"Story {story.story_id}: {status}")
            print(f"  Title: {story.title}")
            if status == "FAIL":
                 print(f"  Desc: {(story.story_description or '')[:100]}...")
            
            if story_failures:
                for f in story_failures:
                    print(f"  - {f}")
                    
        print("-" * 60)
        print(f"Validation Summary: {passed_count} PASSED, {failed_count} FAILED")
        print("NOTE: This dry run only checked basic fields and forbidden terms (simplified).")
        print("Real validation would be stricter but this confirms data shape.")

if __name__ == "__main__":
    dry_run_validation(7)
