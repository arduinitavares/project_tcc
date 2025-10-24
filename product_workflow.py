"""
product_workflow.py

This script defines the main root agent that orchestrates the
product vision and roadmap agents in a sequence.

It uses a LoopAgent as the root, which contains sub-agents for
each step of the workflow, as per the correct ADK pattern.
"""

import os
from typing import Annotated, List

import dotenv
from google.adk.agents import Agent, LoopAgent
from google.adk.models.lite_llm import LiteLlm
from pydantic import BaseModel, Field

# We need the final output schema for our root agent's output
from product_roadmap_agent.agent import OutputSchema as RoadmapOutputSchema
from product_roadmap_agent.agent import root_agent as product_roadmap_agent

# --- Import your "worker" agents and their schemas ---
# We need the agents themselves to pass to 'sub_agents'
from product_vision_agent.agent import root_agent as product_vision_agent

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
# This model will be used by the orchestrator (LoopAgent)
model: LiteLlm = LiteLlm(
    model="openrouter/openai/gpt-5-nano", api_key=os.getenv("OPEN_ROUTER_API_KEY")
)


# --- Define Orchestrator Schemas ---


class InputSchema(BaseModel):
    """
    Input for the *entire workflow*. It only needs the
    initial unstructured text.
    """

    unstructured_requirements: Annotated[
        str,
        Field(
            description=(
                "Raw, unstructured text containing product requirements and " "ideas."
            )
        ),
    ]


class OutputSchema(BaseModel):
    """
    Output for the *entire workflow*. This should be the final
    output from the last agent in the chain (the roadmap agent).
    """

    final_roadmap: Annotated[
        RoadmapOutputSchema, Field(description="The final generated roadmap or draft.")
    ]


# --- Orchestrator Instructions ---
# These instructions tell the LoopAgent *how* to call its sub-agents
# This replaces the need for 'adk.Graph.add_edge()'
ORCHESTRATOR_INSTRUCTIONS = """
You are the master Product Workflow Orchestrator.
Your job is to guide a user's input through a two-step process using
your sub-agents.

DO NOT try to answer the user directly. Your *only* job is to
call your sub-agents in the correct order.

1.  **START:** You will receive the initial `unstructured_requirements`
    from the user.

2.  **STEP 1: Call Vision Agent:**
    * Call your `product_vision_agent` sub-agent.
    * Pass the user's `unstructured_requirements` as its input.
    * You will get a `product_vision_statement` and
        `is_complete` flag in return.

3.  **STEP 2: Handle Vision Output:**
    * **If `is_complete` is `False`:** The vision isn't
        ready. You must stop the workflow. Ask the user the
        `clarifying_questions` you received from the
        `product_vision_agent`.
    * **If `is_complete` is `True`:** The vision is
        ready. Proceed to the next step.

4.  **STEP 3: Call Roadmap Agent:**
    * Call your `product_roadmap_agent` sub-agent.
    * Pass the `product_vision_statement` (from Step 2)
        and the initial `unstructured_requirements` (as the
        `user_input`) to it.

5.  **STEP 4: Final Output:**
    * Take the full output object from the `product_roadmap_agent`.
    * Place this entire object into the `final_roadmap` field of
        your own `OutputSchema` and return it.
"""

# --- Create the Root Orchestrator Agent ---
root_agent: Agent = LoopAgent(
    name="product_workflow_orchestrator",
    description="Orchestrates the full product workflow from vision to roadmap.",
    model=model,
    input_schema=InputSchema,
    output_schema=OutputSchema,
    instruction=ORCHESTRATOR_INSTRUCTIONS,
    # This is the key: we provide the "worker" agents here
    sub_agents=[
        product_vision_agent,
        product_roadmap_agent,
    ],
)


def main():
    """
    Defines sample input and runs the full automated workflow
    via the root LoopAgent.
    """
    print("--- 🚀 Running Full Product Workflow (via LoopAgent) ---")

    # This input has enough info to get a *complete* vision
    complete_requirements = """
    We need to build a new app for busy professionals.
    They have a hard time tracking all their tasks from different apps
    like email, slack, and calendars. It's too much context-switching.
    Our solution should be a mobile-first unified inbox
    that pulls all tasks into one place.
    It needs to be smarter than other task managers, maybe using AI
    to prioritize what's important. Other apps are just basic lists.
    """

    print(f"Initial Input:\n{complete_requirements}\n")

    # This is the input for the *root* agent
    workflow_input = InputSchema(unstructured_requirements=complete_requirements)

    try:
        # Run the entire workflow by calling .run() on the root agent
        # The LoopAgent's logic will handle calling the sub-agents
        final_output: OutputSchema = root_agent.run(workflow_input)

        print("--- ✅ Workflow Finished ---")
        print("\nFinal output (from final_roadmap object):")
        roadmap = final_output.final_roadmap

        print(f"Is Roadmap Complete: {roadmap.is_complete}")
        print(f"Roadmap Draft Themes: {len(roadmap.roadmap_draft)}")

        if not roadmap.is_complete:
            print("\nClarifying Questions (from roadmap_agent):")
            for q in roadmap.clarifying_questions:
                print(f"- {q}")

    except Exception as e:
        # This will catch errors from the sub-agents as well
        print(f"\nAn error occurred while running the workflow: {e}")


if __name__ == "__main__":
    main()
