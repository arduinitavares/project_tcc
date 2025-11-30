"""
Test suite for validating state reconstruction in the product vision agent.

These tests verify that the agent correctly preserves information across
multiple turns (the "anti-goldfish memory" tests).
"""

import pytest
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from orchestrator_agent.agent_tools.product_vision_tool.agent import root_agent


class TestStateReconstruction:
    """Test cases for multi-turn state preservation."""

    @pytest.mark.asyncio
    async def test_basic_accumulation(self):
        """
        Test Case 1: Basic Accumulation
        Turn 1: Identify target user
        Turn 2: Add project name
        Expected: Both values present in Turn 2 output
        """
        # Turn 1: User provides initial idea
        turn1_input = {"unstructured_requirements": "I want a Tinder for Tennis"}
        turn1_response = await root_agent.run(turn1_input)

        # Verify Turn 1 extracted target user
        assert "tennis" in turn1_response.get("product_vision_statement", "").lower()

        # Turn 2: User provides project name
        turn2_input = {"unstructured_requirements": "The project name is NetSet"}
        turn2_response = await root_agent.run(turn2_input)

        # CRITICAL: Turn 2 output must include BOTH project name AND target user
        assert turn2_response.get("project_name") == "NetSet"
        assert "tennis" in turn2_response.get("product_vision_statement", "").lower()

        # Verify target user wasn't set to null
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert (
            "[target user]" not in vision_statement.lower()
        ), "Target user was reset to placeholder despite being known from Turn 1"

    @pytest.mark.asyncio
    async def test_explicit_update(self):
        """
        Test Case 2: Explicit Update
        Turn 1: Set target user to "tennis players"
        Turn 2: Change target user to "pickleball players"
        Expected: Turn 2 output reflects the UPDATE, not the original value
        """
        # Turn 1: Initial target user
        turn1_input = {"unstructured_requirements": "Target users are tennis players"}
        turn1_response = await root_agent.run(turn1_input)
        assert "tennis" in turn1_response.get("product_vision_statement", "").lower()

        # Turn 2: Explicit correction
        turn2_input = {
            "unstructured_requirements": "Actually, target users are pickleball players"
        }
        turn2_response = await root_agent.run(turn2_input)

        # Verify update was applied
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "pickleball" in vision_statement.lower()
        assert (
            "tennis" not in vision_statement.lower()
        ), "Old value persisted despite explicit update"

    @pytest.mark.asyncio
    async def test_partial_information_across_turns(self):
        """
        Test Case 3: Partial Information Across Turns
        Turn 1: Project name
        Turn 2: Target user
        Turn 3: Problem statement
        Expected: Turn 3 output includes ALL THREE components
        """
        # Turn 1: Project name
        turn1_input = {"unstructured_requirements": "The project name is NetSet"}
        turn1_response = await root_agent.run(turn1_input)
        assert turn1_response.get("project_name") == "NetSet"

        # Turn 2: Target user
        turn2_input = {"unstructured_requirements": "Target users are tennis players"}
        turn2_response = await root_agent.run(turn2_input)

        # Verify Turn 2 preserves project name from Turn 1
        assert turn2_response.get("project_name") == "NetSet"
        assert "tennis" in turn2_response.get("product_vision_statement", "").lower()

        # Turn 3: Problem statement
        turn3_input = {
            "unstructured_requirements": "The problem is that it's hard to find tennis partners"
        }
        turn3_response = await root_agent.run(turn3_input)

        # Verify Turn 3 includes ALL components
        assert turn3_response.get("project_name") == "NetSet"
        vision_statement = turn3_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()
        assert (
            "hard to find" in vision_statement.lower()
            or "partners" in vision_statement.lower()
        )

    @pytest.mark.asyncio
    async def test_clarifying_questions_loop(self):
        """
        Test Case 4: Clarifying Questions Loop
        Turn 1: Vague input → Agent asks questions
        Turn 2: User answers ONE question
        Expected: Turn 2 output includes answer + original context
        """
        # Turn 1: Vague input
        turn1_input = {"unstructured_requirements": "Tinder for Tennis"}
        turn1_response = await root_agent.run(turn1_input)

        # Verify agent asked clarifying questions
        assert turn1_response.get("is_complete") is False
        assert len(turn1_response.get("clarifying_questions", [])) > 0

        # Turn 2: Answer only the first question (e.g., project name)
        turn2_input = {"unstructured_requirements": "The project name is NetSet"}
        turn2_response = await root_agent.run(turn2_input)

        # CRITICAL: Turn 2 must preserve "Tennis" context from Turn 1
        assert turn2_response.get("project_name") == "NetSet"
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert (
            "tennis" in vision_statement.lower()
        ), "Original context lost after answering clarifying question"

    @pytest.mark.asyncio
    async def test_null_preservation(self):
        """
        Test Case 5: Null Preservation
        Verify that null/unknown fields remain null until explicitly provided,
        and don't overwrite known fields.
        """
        # Turn 1: Provide only project name
        turn1_input = {"unstructured_requirements": "Project name: NetSet"}
        turn1_response = await root_agent.run(turn1_input)
        assert turn1_response.get("project_name") == "NetSet"

        # Turn 2: Provide only target user (no mention of project name)
        turn2_input = {"unstructured_requirements": "For tennis players"}
        turn2_response = await root_agent.run(turn2_input)

        # Verify project name is preserved (not set to null)
        assert (
            turn2_response.get("project_name") == "NetSet"
        ), "Project name was set to null when not mentioned in Turn 2"

        # Verify target user was added
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()

    @pytest.mark.asyncio
    async def test_multiple_components_single_turn(self):
        """
        Test Case 6: Multiple Components in Single Turn
        Verify agent can extract multiple components from one input
        and preserve them in subsequent turns.
        """
        # Turn 1: Rich input with multiple components
        turn1_input = {
            "unstructured_requirements": (
                "NetSet is a mobile app for tennis players who struggle to find "
                "practice partners. Unlike Facebook groups, it uses skill-based matching."
            )
        }
        turn1_response = await root_agent.run(turn1_input)

        # Verify multiple components extracted
        assert turn1_response.get("project_name") == "NetSet"
        vision_statement = turn1_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()
        assert (
            "mobile app" in vision_statement.lower()
            or "app" in vision_statement.lower()
        )

        # Turn 2: Add one more component (e.g., differentiator)
        turn2_input = {
            "unstructured_requirements": "The key differentiator is real-time availability tracking"
        }
        turn2_response = await root_agent.run(turn2_input)

        # Verify ALL previous components preserved
        assert turn2_response.get("project_name") == "NetSet"
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()
        assert (
            "availability" in vision_statement.lower()
            or "real-time" in vision_statement.lower()
        )


class TestMergeLogic:
    """Test cases for specific merge logic scenarios."""

    @pytest.mark.asyncio
    async def test_preserve_rule(self):
        """
        Merge Rule: Historical value + No mention in current input = PRESERVE
        """
        # Establish historical value
        turn1_input = {"unstructured_requirements": "Target users are tennis players"}
        turn1_response = await root_agent.run(turn1_input)

        # Provide unrelated information (no mention of target user)
        turn2_input = {"unstructured_requirements": "The app will be free to download"}
        turn2_response = await root_agent.run(turn2_input)

        # Verify target user preserved
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()

    @pytest.mark.asyncio
    async def test_update_rule(self):
        """
        Merge Rule: Historical value + New value in current input = UPDATE
        """
        # Establish historical value
        turn1_input = {"unstructured_requirements": "Target users are tennis players"}
        turn1_response = await root_agent.run(turn1_input)

        # Provide explicit update
        turn2_input = {
            "unstructured_requirements": "Change target users to badminton players"
        }
        turn2_response = await root_agent.run(turn2_input)

        # Verify update applied
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "badminton" in vision_statement.lower()
        assert "tennis" not in vision_statement.lower()

    @pytest.mark.asyncio
    async def test_add_rule(self):
        """
        Merge Rule: No historical value + New value in current input = ADD
        """
        # Turn 1: No target user mentioned
        turn1_input = {"unstructured_requirements": "Project name is NetSet"}
        turn1_response = await root_agent.run(turn1_input)

        # Turn 2: Add target user
        turn2_input = {"unstructured_requirements": "For tennis players"}
        turn2_response = await root_agent.run(turn2_input)

        # Verify target user added
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert "tennis" in vision_statement.lower()

    @pytest.mark.asyncio
    async def test_remains_unknown_rule(self):
        """
        Merge Rule: No historical value + No mention in current input = REMAINS UNKNOWN
        """
        # Turn 1: Provide only project name
        turn1_input = {"unstructured_requirements": "Project name is NetSet"}
        turn1_response = await root_agent.run(turn1_input)

        # Turn 2: Provide only target user (no mention of problem)
        turn2_input = {"unstructured_requirements": "For tennis players"}
        turn2_response = await root_agent.run(turn2_input)

        # Verify "problem" component remains unknown (placeholder in vision)
        vision_statement = turn2_response.get("product_vision_statement", "")
        assert (
            "[problem]" in vision_statement.lower()
            or "who [" in vision_statement.lower()
        )


@pytest.mark.integration
class TestRealWorldScenarios:
    """Integration tests simulating real user conversations."""

    @pytest.mark.asyncio
    async def test_incremental_refinement(self):
        """
        Simulate a user gradually refining their idea across 5 turns.
        """
        conversation = [
            "I want to build something for tennis players",
            "It's called NetSet",
            "The problem is finding practice partners",
            "It's a mobile app",
            "Unlike Facebook groups, it has skill-based matching",
        ]

        previous_response = None
        for turn_num, user_input in enumerate(conversation, start=1):
            response = await root_agent.run({"unstructured_requirements": user_input})

            # Verify cumulative state growth
            if turn_num >= 2:
                # From Turn 2 onwards, verify previous information is preserved
                vision_statement = response.get("product_vision_statement", "")
                assert (
                    "tennis" in vision_statement.lower()
                ), f"Turn {turn_num}: Lost 'tennis' from Turn 1"

            if turn_num >= 3:
                assert (
                    response.get("project_name") == "NetSet"
                ), f"Turn {turn_num}: Lost project name from Turn 2"

            previous_response = response

        # Final verification: All components present
        final_vision = previous_response.get("product_vision_statement", "")
        assert "tennis" in final_vision.lower()
        assert "netset" in previous_response.get("project_name", "").lower()
        assert "partners" in final_vision.lower() or "practice" in final_vision.lower()
        assert "mobile" in final_vision.lower() or "app" in final_vision.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
