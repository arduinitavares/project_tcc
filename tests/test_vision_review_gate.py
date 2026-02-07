"""
Tests for the Vision Review approval gate.

Bug: ROUTING_MODE instruction embedded an inline save recipe
(save_vision_tool + link_spec_to_product) that let the LLM
bypassed the VISION_REVIEW approval gate after product_vision_tool
returned is_complete=True.

Fix contract:
1. ROUTING_MODE instruction must NOT tell the agent to call
   save_vision_tool directly — it must STOP after product_vision_tool.
2. Spec linking happens INSIDE save_vision_tool (Pre-Phase / authority
   compilation before vision persistence).  VISION_PERSISTENCE is a
   pure confirmation state with no spec/authority tools.
3. FSM transitions remain correct (already passing).
"""
import re
import unittest

from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState


class TestVisionReviewGate(unittest.TestCase):
    """Ensure the LLM cannot bypass the vision approval gate."""

    def setUp(self):
        self.controller = FSMController()

    # --- FSM transition correctness (sanity) ---

    def test_routing_mode_vision_complete_transitions_to_review(self):
        """product_vision_tool(is_complete=True) in ROUTING_MODE → VISION_REVIEW."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "product_vision_tool",
            {"is_complete": True},
            "start project",
        )
        self.assertEqual(next_state, OrchestratorState.VISION_REVIEW)

    def test_vision_review_save_transitions_to_persistence(self):
        """save_vision_tool in VISION_REVIEW → VISION_PERSISTENCE."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "save_vision_tool",
            {},
            "save",
        )
        self.assertEqual(next_state, OrchestratorState.VISION_PERSISTENCE)

    # --- Instruction-level guard: no inline save recipe in ROUTING ---

    def test_routing_instruction_does_not_embed_save_recipe(self):
        """ROUTING_MODE instruction must not tell the agent to chain
        save_vision_tool immediately after product_vision_tool.
        It should contain an explicit STOP directive after the vision call."""
        routing_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        instruction = routing_def.instruction

        # The instruction should NOT contain a recipe that says
        # "call save_vision_tool" inside the new-project-with-file flow.
        # We look for the problematic pattern: product_vision_tool followed
        # by save_vision_tool within the same numbered routing block.
        section3_match = re.search(
            r"New Project with Specification File.*?(?=\d+\.\s\*\*|$)",
            instruction,
            re.DOTALL,
        )
        self.assertIsNotNone(section3_match, "Section 3 not found in ROUTING instruction")
        section3_text = section3_match.group()

        self.assertNotIn(
            "save_vision_tool",
            section3_text,
            "ROUTING section 3 must NOT contain an inline save_vision_tool recipe. "
            "The agent should STOP after product_vision_tool and let the FSM "
            "transition to VISION_REVIEW for user approval.",
        )

    def test_routing_instruction_does_not_embed_spec_save_recipe(self):
        """ROUTING_MODE section 4 (pasted content) must not embed
        save_project_specification inline either."""
        routing_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        instruction = routing_def.instruction

        section4_match = re.search(
            r"New Project with Pasted Content.*?(?=\d+\.\s\*\*|$)",
            instruction,
            re.DOTALL,
        )
        self.assertIsNotNone(section4_match, "Section 4 not found in ROUTING instruction")
        section4_text = section4_match.group()

        self.assertNotIn(
            "save_vision_tool",
            section4_text,
            "ROUTING section 4 must NOT contain an inline save_vision_tool recipe.",
        )

    # --- VISION_PERSISTENCE is a pure confirmation state ---

    def test_vision_persistence_does_not_have_link_spec_to_product(self):
        """VISION_PERSISTENCE must NOT include link_spec_to_product.
        Spec linking now happens inside save_vision_tool (Pre-Phase)."""
        persistence_def = STATE_REGISTRY[OrchestratorState.VISION_PERSISTENCE]
        tool_names = [
            getattr(t, "__name__", None) or getattr(t, "name", None) or str(t)
            for t in persistence_def.tools
        ]
        self.assertNotIn(
            "link_spec_to_product",
            tool_names,
            "VISION_PERSISTENCE must NOT contain link_spec_to_product. "
            "Spec linking is handled internally by save_vision_tool.",
        )

    def test_routing_mode_does_not_have_link_spec_to_product(self):
        """ROUTING_MODE must NOT include link_spec_to_product."""
        routing_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        tool_names = [
            getattr(t, "__name__", None) or getattr(t, "name", None) or str(t)
            for t in routing_def.tools
        ]
        self.assertNotIn(
            "link_spec_to_product",
            tool_names,
            "ROUTING_MODE must NOT contain link_spec_to_product.",
        )

    def test_vision_persistence_only_has_backlog_primer(self):
        """VISION_PERSISTENCE tools should contain only backlog_primer_tool
        since it is a pure confirmation state."""
        persistence_def = STATE_REGISTRY[OrchestratorState.VISION_PERSISTENCE]
        tool_names = [
            getattr(t, "__name__", None) or getattr(t, "name", None) or str(t)
            for t in persistence_def.tools
        ]
        self.assertEqual(
            tool_names,
            ["backlog_primer_tool"],
            "VISION_PERSISTENCE should only have backlog_primer_tool.",
        )


if __name__ == "__main__":
    unittest.main()
