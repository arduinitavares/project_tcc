import json
from typing import Any, Dict, Optional, Set, cast

from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from orchestrator_agent.agent_tools.story_pipeline.util.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.util.constants import (
    KEY_STORY_DRAFT, KEY_SPEC_VALIDATION_RESULT, KEY_REFINEMENT_RESULT,
    KEY_EXIT_LOOP_DIAGNOSTIC
)
from orchestrator_agent.agent_tools.story_pipeline.util.logging import PipelineLogger
from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import create_story_draft_agent
from utils.schemes import StoryDraftInput
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import create_story_refiner_agent
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_validation_loop
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent
from orchestrator_agent.agent_tools.story_pipeline.util.ui import (
    display_subagent_output,
    display_subagent_tool_call,
    display_subagent_tool_response,
    display_subagent_input
)
from orchestrator_agent.agent_tools.story_pipeline.util.helpers import (
    build_story_draft_input_payload,
    extract_agent_inputs
)





def create_pipeline_runner(story_input: ProcessStoryInput, session_service: InMemorySessionService):
    """Creates the ADK runner configured for the pipeline strategy."""
    if story_input.enable_story_refiner and story_input.enable_spec_validator:
        agent_to_run = story_validation_loop
    elif story_input.enable_story_refiner:
        agent_to_run = SequentialAgent(
            name="StorySequentialNoSpecValidator",
            sub_agents=[create_story_draft_agent(), create_story_refiner_agent()],
            description="Drafts and refines a story (no spec validator).",
        )
    else:
        agent_to_run = SelfHealingAgent(agent=create_story_draft_agent(), max_retries=3)

    return Runner(
        agent=agent_to_run,
        app_name="story_pipeline",
        session_service=session_service,
    ), agent_to_run


async def execute_pipeline(
    runner: Runner,
    session_id: str,
    story_input: ProcessStoryInput,
    logger: PipelineLogger,
    session_service: InMemorySessionService
) -> Dict[str, Any]:
    """Runs the ADK pipeline and returns the final state."""
    current_session = await session_service.get_session(
        app_name="story_pipeline",
        user_id="pipeline_user",
        session_id=session_id,
    )
    state = current_session.state if current_session and current_session.state else {}
    payload = build_story_draft_input_payload(state, story_input)
    story_draft_input = StoryDraftInput.model_validate(payload)
    prompt_text = story_draft_input.model_dump_json()

    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)],
    )

    # Log sub-agent input payloads (formatted like main.py)
    display_subagent_input("[SUB-AGENT INPUT: Prompt]", {"text": prompt_text})
    display_subagent_input(
        "[SUB-AGENT INPUT: StoryDraftAgent]",
        story_draft_input.model_dump(),
    )

    # State tracking
    last_story_draft: Optional[Any] = None
    last_spec_validation_result: Optional[Any] = None
    last_refinement_result: Optional[Any] = None
    last_exit_loop_diagnostic: Optional[Any] = None
    current_iteration: int = 0
    seen_drafts: Set[int] = set()
    last_author_input_logged: Optional[str] = None

    try:
        async for event in runner.run_async(
            user_id="pipeline_user",
            session_id=session_id,
            new_message=new_message,
        ):
            # --- START REAL-TIME LOGGING WITH RICH PANELS ---
            author = getattr(event, 'author', None) or 'unknown'
            
            if event.content and event.content.parts:
                if author and author != last_author_input_logged:
                    try:
                        current_session = await session_service.get_session(
                            app_name="story_pipeline",
                            user_id="pipeline_user",
                            session_id=session_id,
                        )
                        if current_session and current_session.state:
                            inputs = extract_agent_inputs(author, current_session.state)
                            if inputs is not None:
                                display_subagent_input(
                                    f"[SUB-AGENT INPUT: {author}]",
                                    inputs,
                                )
                                last_author_input_logged = author
                    except Exception:
                        pass
                for part in event.content.parts:
                    if part.text:
                        # Display agent output in Rich Panel
                        display_subagent_output(author, part.text.strip())

                    if part.function_call:
                        # Display tool call in Rich Panel
                        display_subagent_tool_call(
                            author,
                            part.function_call.name or "unknown_tool",
                            part.function_call.args
                        )

                    if part.function_response:
                        # Display tool response in Rich Panel
                        display_subagent_tool_response(
                            author,
                            part.function_response.name or "unknown_tool",
                            part.function_response.response
                        )
            # --- END REAL-TIME LOGGING ---

            # Live progress logging logic
            try:
                current_session = await session_service.get_session(
                    app_name="story_pipeline",
                    user_id="pipeline_user",
                    session_id=session_id,
                )
                if current_session and current_session.state:
                    state = current_session.state

                    # Draft detection
                    story_draft = state.get(KEY_STORY_DRAFT)
                    if story_draft and story_draft != last_story_draft:
                        draft_hash = hash(str(story_draft))
                        if draft_hash not in seen_drafts:
                            seen_drafts.add(draft_hash)
                            current_iteration += 1
                            logger.log(f"\n   Iteration {current_iteration}")

                        last_story_draft = story_draft
                        draft_data: Dict[str, Any] = {}
                        if isinstance(story_draft, dict):
                            draft_data = cast(Dict[str, Any], story_draft)
                        if isinstance(story_draft, str):
                            try:
                                draft_data = json.loads(story_draft)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        # Intermediate cleanup for display
                        if not story_input.include_story_points and draft_data.get("story_points") is not None:
                            draft_data["story_points"] = None
                            state[KEY_STORY_DRAFT] = draft_data

                        if draft_data:
                            # We don't have _ensure_spec_version_metadata here easily, but it's handled in post-processing
                            # Just log details
                            title = draft_data.get("title", "")
                            desc = draft_data.get("description", "")[:100]
                            logger.log("   Draft:")
                            logger.log(f"      Title: {title}")
                            logger.log(f"      Story: {desc}...")
                            if story_input.include_story_points:
                                points = draft_data.get("story_points", "?")
                                logger.log(f"      Points: {points}")

                    # Spec Validation detection
                    spec_validation_result = state.get(KEY_SPEC_VALIDATION_RESULT)
                    if spec_validation_result and spec_validation_result != last_spec_validation_result:
                        last_spec_validation_result = spec_validation_result
                        spec_data: Dict[str, Any] = spec_validation_result if isinstance(spec_validation_result, dict) else {}
                        if isinstance(spec_validation_result, str):
                            try:
                                spec_data = json.loads(spec_validation_result)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        if spec_data:
                            is_compliant = bool(spec_data.get("is_compliant", True))
                            spec_issues = spec_data.get("issues", [])
                            spec_suggestions = spec_data.get("suggestions", [])
                            domain_compliance = spec_data.get("domain_compliance", {})

                            status_text = "OK" if is_compliant else "VIOLATION"
                            logger.log(f"   Spec: {status_text}")

                            if domain_compliance:
                                domain_name = domain_compliance.get("matched_domain", "general")
                                bound_count = domain_compliance.get("bound_requirement_count", 0)
                                satisfied = domain_compliance.get("satisfied_count", 0)
                                critical_gaps = domain_compliance.get("critical_gaps", [])

                                logger.log(
                                    f"      Domain: {domain_name} ({satisfied}/{bound_count} requirements)"
                                )
                                if critical_gaps:
                                    logger.log(f"      Critical Gaps ({len(critical_gaps)}):")
                                    for gap in critical_gaps[:3]:
                                        logger.log(f"        - {gap}")

                            if (not is_compliant) and spec_issues:
                                logger.log("      Spec issues:")
                                for issue in spec_issues[:3]:
                                    logger.log(f"        - {issue}")

                            if spec_suggestions:
                                logger.log("      Spec fixes needed:")
                                for sug in spec_suggestions[:3]:
                                    logger.log(f"        - {sug}")

                    # Exit Loop Diagnostic
                    exit_loop_diag = state.get(KEY_EXIT_LOOP_DIAGNOSTIC)
                    if exit_loop_diag and exit_loop_diag != last_exit_loop_diagnostic:
                        last_exit_loop_diagnostic = exit_loop_diag
                        diag_data = exit_loop_diag if isinstance(exit_loop_diag, dict) else {}
                        if isinstance(exit_loop_diag, str):
                            try:
                                diag_data = json.loads(exit_loop_diag)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        if diag_data:
                            loop_exit = bool(diag_data.get("loop_exit", False))
                            blocked_by = diag_data.get("blocked_by")
                            reason = diag_data.get("reason", "")
                            if loop_exit:
                                logger.log("   Loop exit: ready")
                            else:
                                logger.log(f"   Loop exit: blocked ({blocked_by})")
                            if reason:
                                logger.log(f"      Reason: {reason}")

                    # Refinement Result
                    refinement_result = state.get(KEY_REFINEMENT_RESULT)
                    if refinement_result and refinement_result != last_refinement_result:
                        last_refinement_result = refinement_result
                        ref_data = refinement_result if isinstance(refinement_result, dict) else {}
                        if isinstance(refinement_result, str):
                            try:
                                ref_data = json.loads(refinement_result)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        if ref_data:
                            is_valid = ref_data.get("is_valid", False)
                            refined = ref_data.get("refined_story", {})
                            notes = ref_data.get("refinement_notes", "")
                            refinement_applied = ref_data.get("refinement_applied", False)

                            refinement_status = "Changes applied" if refinement_applied else "No changes"
                            logger.log(f"   Refined: {refinement_status}")

                            if refined:
                                title = refined.get('title', '')
                                logger.log(f"      Title: {title}")
                                ac_raw = refined.get('acceptance_criteria', '')
                                if ac_raw:
                                    ac_list = [line.strip() for line in ac_raw.strip().split('\n') if line.strip().startswith('-')]
                                    logger.log(f"      AC Count: {len(ac_list)} criteria")
                                    for ac in ac_list[:2]:
                                        ac_preview = ac[:60] + "..." if len(ac) > 60 else ac
                                        logger.log(f"        - {ac_preview}")
                            if notes:
                                logger.log(
                                    f"      Notes: {notes[:100]}{'...' if len(notes) > 100 else ''}"
                                )

            except Exception as e:
                if logger.should_dump_debug():
                    logger.log(f"State inspection error: {e}")

        # Fetch final state
        final_session = await session_service.get_session(
            app_name="story_pipeline",
            user_id="pipeline_user",
            session_id=session_id,
        )
        final_state = final_session.state if final_session else {}
        final_state["_local_iterations"] = max(current_iteration, 1)
        return final_state

    except Exception as e:
        logger.log(f"Pipeline error: {e}")
        raise
