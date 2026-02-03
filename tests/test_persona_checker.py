import pytest
from orchestrator_agent.agent_tools.story_pipeline.steps.persona_checker import (
    extract_persona_from_story,
    validate_persona,
    auto_correct_persona,
    are_personas_equivalent,
)

def test_extract_persona_standard_format():
    """Test persona extraction from standard format."""
    description = "As an automation engineer, I want to configure rules so that extraction is accurate."
    result = extract_persona_from_story(description)
    assert result == "automation engineer"

def test_extract_persona_with_article_a():
    """Test extraction with 'a' article."""
    description = "As a software engineer, I want to deploy the system..."
    result = extract_persona_from_story(description)
    assert result == "software engineer"

def test_extract_persona_ending_with_comma():
    """Test extraction with comma."""
    description = "As a software engineer, I want..."
    result = extract_persona_from_story(description)
    assert result == "software engineer"

def test_extract_persona_ending_with_i_want():
    """Test extraction without comma."""
    description = "As a software engineer I want..."
    result = extract_persona_from_story(description)
    assert result == "software engineer"

def test_extract_persona_plural_in_text():
    """Test extracting plural, though normalization handles it separately."""
    description = "As a software engineers, I want..."
    result = extract_persona_from_story(description)
    assert result == "software engineers" # Extracted as is

def test_validate_persona_correct():
    """Test validation with correct persona."""
    description = "As an automation engineer, I want..."
    result = validate_persona(description, "automation engineer")
    assert result.is_valid == True
    assert result.violation_message is None

def test_validate_persona_mismatch():
    """Test validation detects persona mismatch."""
    description = "As a data annotator, I want to label symbols..."
    result = validate_persona(description, "automation engineer")
    assert result.is_valid == False
    assert "data annotator" in result.violation_message
    assert result.extracted_persona == "data annotator"

def test_validate_persona_synonyms():
    """Test validation handles synonyms."""
    description = "As a control engineer, I want..."
    # "control engineer" maps to "automation engineer"
    result = validate_persona(description, "automation engineer")
    assert result.is_valid == True
    assert result.extracted_persona == "control engineer"

def test_auto_correct_persona_simple():
    """Test automatic persona correction."""
    story = {
        "description": "As a software engineer, I want to configure rules...",
        "title": "Configure extraction rules"
    }
    corrected = auto_correct_persona(story, "automation engineer")
    assert "As an automation engineer, I want" in corrected["description"]
    assert "software engineer" not in corrected["description"]

def test_auto_correct_persona_no_comma():
    """Test automatic persona correction without comma."""
    story = {
        "description": "As a software engineer I want to configure rules...",
        "title": "Configure extraction rules"
    }
    corrected = auto_correct_persona(story, "automation engineer")
    assert "As an automation engineer I want" in corrected["description"]

def test_auto_correct_persona_wrong_article():
    """Test correction fixes article too."""
    story = {
        "description": "As a automation engineer, I want..."
    }
    corrected = auto_correct_persona(story, "automation engineer")
    # Should fix "As a" -> "As an"
    assert "As an automation engineer, I want" in corrected["description"]

def test_auto_correct_persona_prepend():
    """Test correction prepends if missing."""
    story = {
        "description": "I want to configure rules..."
    }
    corrected = auto_correct_persona(story, "automation engineer")
    assert corrected["description"].startswith("As an automation engineer, I want")

def test_extract_persona_with_slash():
    """Test extraction when persona contains forward slash (ML/Data Engineer)."""
    description = "As a ML/Data Engineer responsible for running inference pipelines, I want to ingest P&ID documents..."
    result = extract_persona_from_story(description)
    assert result == "ml/data engineer responsible for running inference pipelines"

def test_extract_persona_with_embedded_commas():
    """Test extraction when persona contains embedded commas."""
    description = "As a ML/Data Engineer responsible for running inference pipelines on industrial diagrams, diagnosing extraction quality, swapping models, and ensuring outputs are reproducible and ready for downstream review and retraining, I want to ingest documents..."
    result = extract_persona_from_story(description)
    assert result == "ml/data engineer responsible for running inference pipelines on industrial diagrams, diagnosing extraction quality, swapping models, and ensuring outputs are reproducible and ready for downstream review and retraining"

def test_extract_persona_with_hyphen():
    """Test extraction when persona contains hyphen."""
    description = "As a senior-level engineer, I want to configure rules..."
    result = extract_persona_from_story(description)
    assert result == "senior-level engineer"

def test_validate_persona_with_special_chars():
    """Test validation with persona containing special characters."""
    description = "As a ML/Data Engineer, I want to diagnose extraction quality..."
    result = validate_persona(description, "ML/Data Engineer")
    assert result.is_valid == True
    assert result.extracted_persona == "ml/data engineer"

def test_persona_synonyms():
    """Test synonym matching."""
    assert are_personas_equivalent("automation engineer", "control engineer") == True
    assert are_personas_equivalent("Automation Engineer", "automation engineer") == True
    assert are_personas_equivalent("automation engineer", "data scientist") == False
