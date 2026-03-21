with open("tests/test_api_dashboard.py", "r") as f:
    content = f.read()

target = """    def fake_single(session_id):
        call_counts["get_session_status"] += 1
        return workflow.get_session_status(session_id)

    monkeypatch.setattr(workflow, "get_session_states_batch", fake_batch)
    monkeypatch.setattr(workflow, "get_session_status", fake_single)"""

replacement = """    original_single = workflow.get_session_status

    def fake_single(session_id):
        call_counts["get_session_status"] += 1
        return original_single(session_id)

    monkeypatch.setattr(workflow, "get_session_states_batch", fake_batch)
    monkeypatch.setattr(workflow, "get_session_status", fake_single)"""

if target in content:
    content = content.replace(target, replacement)
    with open("tests/test_api_dashboard.py", "w") as f:
        f.write(content)
    print("Success")
else:
    print("Failed to find target")
