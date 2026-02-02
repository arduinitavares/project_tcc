import copy
import json
from typing import Any, Dict, Optional, Set

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.pipeline_constants import (
    KEY_STORY_DRAFT, KEY_SPEC_VALIDATION_RESULT, KEY_REFINEMENT_RESULT,
    KEY_EXIT_LOOP_DIAGNOSTIC, GREEN, RED, YELLOW, CYAN, MAGENTA, RESET
)
from orchestrator_agent.agent_tools.story_pipeline.pipeline_logging import PipelineLogger
from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import story_draft_agent
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import story_refiner_agent
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_validation_loop
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent


def _clone_agent(agent: BaseAgent) -> BaseAgent:
    if isinstance(agent, LlmAgent):
        return LlmAgent(
            name=agent.name,
            model=agent.model,
            instruction=agent.instruction,
            description=getattr(agent, "description", None),
            output_key=getattr(agent, "output_key", None),
            output_schema=getattr(agent, "output_schema", None),
            disallow_transfer_to_parent=getattr(agent, "disallow_transfer_to_parent", False),
            disallow_transfer_to_peers=getattr(agent, "disallow_transfer_to_peers", False),
        )
    cloned = copy.deepcopy(agent)
    if hasattr(cloned, "parent"):
        setattr(cloned, "parent", None)
    if hasattr(cloned, "_parent"):
        setattr(cloned, "_parent", None)
    return cloned


def create_pipeline_runner(story_input: ProcessStoryInput, session_service: InMemorySessionService):
    """Creates the ADK runner configured for the pipeline strategy."""
    if story_input.enable_story_refiner:
        if story_input.enable_spec_validator:
            agent_to_run = story_validation_loop
        else:
            agent_to_run = SequentialAgent(
                name="StorySequentialNoSpecValidator",
                sub_agents=[
                    SelfHealingAgent(agent=_clone_agent(story_draft_agent), max_retries=3),
                    SelfHealingAgent(agent=_clone_agent(story_refiner_agent), max_retries=3),
                ],
                description="Drafts and refines a story (no spec validator).",
            )
    else:
        agent_to_run = story_draft_agent

    return Runner(
        agent=agent_to_run,
        app_name="story_pipeline",
        session_service=session_service,
    ), agent_to_run


async def execute_pipeline(
    runner: Runner,
    session_id: str,
    feature_title: str,
    story_input: ProcessStoryInput,
    logger: PipelineLogger,
    session_service: InMemorySessionService
) -> Dict[str, Any]:
    """Runs the ADK pipeline and returns the final state."""

    prompt_text = f"Generate a user story for feature: {feature_title}"
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)],
    )

    # State tracking
    last_story_draft: Optional[Any] = None
    last_spec_validation_result: Optional[Any] = None
    last_refinement_result: Optional[Any] = None
    last_exit_loop_diagnostic: Optional[Any] = None
    current_iteration: int = 0
    seen_drafts: Set[int] = set()

    try:
        async for _ in runner.run_async(
            user_id="pipeline_user",
            session_id=session_id,
            new_message=new_message,
        ):
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
                            logger.log(f"\n{MAGENTA}   ╭─ Iteration {current_iteration} ─────────────────────────────────╮{RESET}")

                        last_story_draft = story_draft
                        draft_data: Dict[str, Any] = (
                            story_draft if isinstance(story_draft, dict) else {}
                        )
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
                            logger.log(f"{CYAN}   │ 📝 DRAFT:{RESET}")
                            logger.log(f"{CYAN}   │{RESET}    Title: {title}")
                            logger.log(f"{CYAN}   │{RESET}    Story: {desc}...")
                            if story_input.include_story_points:
                                points = draft_data.get("story_points", "?")
                                logger.log(f"{CYAN}   │{RESET}    Points: {points}")

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

                            status_icon = "✅" if is_compliant else "❌"
                            status_color = GREEN if is_compliant else RED
                            logger.log(f"{YELLOW}   │ 🧾 SPEC: {status_color}{status_icon} {'OK' if is_compliant else 'VIOLATION'}{RESET}")

                            if domain_compliance:
                                domain_name = domain_compliance.get("matched_domain", "general")
                                bound_count = domain_compliance.get("bound_requirement_count", 0)
                                satisfied = domain_compliance.get("satisfied_count", 0)
                                critical_gaps = domain_compliance.get("critical_gaps", [])

                                logger.log(f"{YELLOW}   │{RESET}    Domain: {domain_name} ({satisfied}/{bound_count} requirements)")
                                if critical_gaps:
                                    logger.log(f"{RED}   │{RESET}    Critical Gaps ({len(critical_gaps)}):")
                                    for gap in critical_gaps[:3]:
                                        logger.log(f"{RED}   │{RESET}      ⚠ {gap}")

                            if (not is_compliant) and spec_issues:
                                logger.log(f"{RED}   │{RESET}    Spec issues:")
                                for issue in spec_issues[:3]:
                                    logger.log(f"{RED}   │{RESET}      • {issue}")

                            if spec_suggestions:
                                logger.log(f"{YELLOW}   │{RESET}    Spec fixes needed:")
                                for sug in spec_suggestions[:3]:
                                    logger.log(f"{YELLOW}   │{RESET}      → {sug}")

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
                                logger.log(f"{GREEN}   │ 🧰 LOOP EXIT: ready{RESET}")
                            else:
                                logger.log(f"{YELLOW}   │ 🧰 LOOP EXIT: blocked ({blocked_by}){RESET}")
                            if reason:
                                logger.log(f"{YELLOW}   │{RESET}      → {reason}")

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

                            status_color = GREEN if is_valid else YELLOW
                            refinement_icon = "🔧" if refinement_applied else "✓"
                            logger.log(f"{status_color}   │ ✨ REFINED: {refinement_icon} {'Changes applied' if refinement_applied else 'No changes'}{RESET}")

                            if refined:
                                title = refined.get('title', '')
                                logger.log(f"{status_color}   │{RESET}    Title: {title}")
                                ac_raw = refined.get('acceptance_criteria', '')
                                if ac_raw:
                                    ac_list = [line.strip() for line in ac_raw.strip().split('\n') if line.strip().startswith('-')]
                                    logger.log(f"{status_color}   │{RESET}    AC Count: {len(ac_list)} criteria")
                                    for ac in ac_list[:2]:
                                        ac_preview = ac[:60] + "..." if len(ac) > 60 else ac
                                        logger.log(f"{status_color}   │{RESET}      • {ac_preview}")
                            if notes:
                                logger.log(f"{status_color}   │{RESET}    Notes: {notes[:100]}{'...' if len(notes) > 100 else ''}")
                            logger.log(f"{MAGENTA}   ╰────────────────────────────────────────────────╯{RESET}")

            except Exception as e:
                # Log but continue - state inspection shouldn't crash the pipeline
                # Use standard print if logger fails, but logger should be safe
                pass

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
        logger.log(f"   [Pipeline Error] {e}")
        raise e
