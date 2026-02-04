import re
from pathlib import Path

def test_instruction_states_are_unique():
    """
    Parses orchestrator_agent/instructions.txt and verifies that:
    1. All STATE identifiers are unique.
    2. STATE 20 is 'VIEW STORY DETAILS MODE'.
    3. STATE 22 is 'SPEC COMPILE MODE'.
    """
    instructions_path = Path("orchestrator_agent/instructions.txt")
    if not instructions_path.exists():
        # Fallback if running from a different directory
        instructions_path = Path(__file__).parents[1] / "orchestrator_agent/instructions.txt"

    assert instructions_path.exists(), "instructions.txt not found"

    content = instructions_path.read_text()

    # Regex to find lines like "## STATE 20 — VIEW STORY DETAILS MODE"
    state_pattern = re.compile(r"^## STATE (\d+)\s+[—–-]\s+(.+)$", re.MULTILINE)

    states = {}
    for match in state_pattern.finditer(content):
        state_id = int(match.group(1))
        state_name = match.group(2).strip()

        # Check for duplicates
        if state_id in states:
            raise AssertionError(f"Duplicate STATE {state_id} found! Original: '{states[state_id]}', Duplicate: '{state_name}'")

        states[state_id] = state_name

    # Verify specific states
    assert 20 in states, "STATE 20 not found"
    assert "VIEW STORY DETAILS MODE" in states[20], f"STATE 20 should be 'VIEW STORY DETAILS MODE', got '{states[20]}'"

    assert 22 in states, "STATE 22 not found"
    assert "SPEC COMPILE MODE" in states[22], f"STATE 22 should be 'SPEC COMPILE MODE', got '{states[22]}'"

    # Ensure no other states map to these names (reverse check)
    name_to_id = {v: k for k, v in states.items()}

    # Check if any other state has "SPEC COMPILE MODE" in its name
    for s_id, s_name in states.items():
        if "SPEC COMPILE MODE" in s_name and s_id != 22:
             raise AssertionError(f"Duplicate SPEC COMPILE MODE found at STATE {s_id}")
        if "VIEW STORY DETAILS MODE" in s_name and s_id != 20:
             raise AssertionError(f"Duplicate VIEW STORY DETAILS MODE found at STATE {s_id}")

if __name__ == "__main__":
    test_instruction_states_are_unique()
    print("Test passed!")
