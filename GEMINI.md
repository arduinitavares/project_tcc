# Project Overview

This is a Python project designed to assist with product management by leveraging AI agents. It uses the Google ADK (Agent Development Kit) to orchestrate a workflow that transforms unstructured product requirements into a structured product vision and then into a high-level product roadmap. The project uses `uv` for dependency management and `sqlite` for session persistence.

## Key Technologies

*   **Python 3.12+**
*   **Google ADK:** For agent orchestration (`Runner`, `LoopAgent`, `DatabaseSessionService`).
*   **LiteLLM:** For interacting with various LLM providers (configured with `openrouter/openai/gpt-5-nano`).
*   **Pydantic:** For defining data schemas and validation.
*   **Dotenv:** For managing environment variables.
*   **asyncio:** For asynchronous programming.
*   **SQLite:** For persistent storage of agent session data (`my_agent_data.db`).

## Architecture

The system is built around a `LoopAgent` named `product_workflow_orchestrator` which acts as the main coordinator. It manages two primary sub-agents:

1.  **`product_vision_agent`**: This agent's role is to take unstructured product requirements and, using a predefined template, generate a product vision statement. If any critical information is missing, it will ask clarifying questions to the user.
2.  **`product_roadmap_agent`**: Once a product vision is established, this agent guides the user through creating a high-level agile product roadmap. It helps in identifying requirements, grouping them into themes, prioritizing them, and assigning high-level timeframes (`Now`, `Next`, `Later`).

The `main.py` script provides an interactive command-line interface for directly engaging with the `product_vision_agent`, handling session management and state persistence. The `product_workflow.py` script demonstrates the end-to-end orchestration of both agents by the `LoopAgent`.

## Development Conventions

*   **Agent-based architecture:** The project heavily relies on the Google ADK for defining and orchestrating AI agents.
*   **Schema-driven communication:** Pydantic schemas are used to define the input and output structures for agents, ensuring clear data contracts.
*   **Instruction-based agents:** Agents are guided by detailed `instructions.txt` files that define their role, process, and how they should interact with users and other agents.
*   **Session persistence:** Agent conversations and state are persisted using a SQLite database, allowing for multi-turn interactions.
*   **Asynchronous operations:** `asyncio` is used for handling asynchronous agent calls.

## Building and Running

### Dependencies

The project uses `uv` for dependency management. To install dependencies, navigate to the project root and run:

```bash
uv sync
```

### Running the Product Vision Agent (Interactive)

To interact with the `product_vision_agent` directly via a CLI:

```bash
python main.py
```

### Running the Full Product Workflow (Orchestrated)

To run the complete workflow orchestrated by the `LoopAgent` (vision -> roadmap):

```bash
python product_workflow.py
```
