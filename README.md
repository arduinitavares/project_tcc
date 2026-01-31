# 🤖 Autonomous Agile Management Platform

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Google ADK](https://img.shields.io/badge/Google-ADK-orange.svg)](https://github.com/google/adk-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **A multi-agent AI system that simulates Scrum roles to reduce cognitive load for small development teams (1-4 developers).**

This project is part of a **TCC (Trabalho de Conclusão de Curso)** research initiative exploring how AI agents can autonomously orchestrate Agile workflows, from product vision to sprint execution, utilizing a **Spec-Driven Architecture**.

---

## ✨ Features

### 🎯 Complete Agile Workflow Pipeline
```
Vision → Specification Authority → Roadmap → Features → User Stories → Sprint Planning → Execution
```

### 🧠 Intelligent Agents
| Agent | Role | Capabilities |
|-------|------|--------------|
| **Product Vision Agent** | Product Owner | Guides users through 7-component vision creation via multi-turn conversation |
| **Spec Authority Compiler** | Architect | Compiles technical specifications into deterministic authority artifacts |
| **Roadmap Agent** | Product Owner | Converts vision & spec into prioritized themes with Now/Next/Later timeframes |
| **Story Pipeline** | Developer Support | Generates INVEST-ready user stories with spec validation & authority pinning |
| **Sprint Planning** | Scrum Master | Plans sprints with capacity modeling and team auto-creation |
| **Sprint Execution** | Scrum Master | Tracks progress, status updates, and velocity metrics |

### 🛠️ Key Capabilities
- **Spec-Driven Development**: Single source of truth via `SpecRegistry` and deterministic validation gates.
- **Draft → Review → Commit Pattern**: All artifacts go through validation before persistence.
- **Authority Pinning**: Story acceptance depends on compiled authority, preventing scope creep.
- **Stateless Agents**: Predictable behavior with state injection via JSON.
- **WorkflowEvent Metrics**: Built-in tracking for TCC evaluation (NASA-TLX, cycle time).

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                        │
│         (State Machine with 18 States + Routing)            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Vision    │  │  Spec Auth  │  │   Roadmap Agent     │  │
│  │   Agent     │  │  Compiler   │  │   (Context-Aware)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                          │                                  │
│                   ┌──────▼──────┐                           │
│                   │ Spec Registry│                           │
│                   │ & Authority │                           │
│                   └──────┬──────┘                           │
│                          │                                  │
│  ┌───────────────────────▼─────────────────────────────────┐│
│  │              Story Pipeline & Sprint Planning            ││
│  │  (Spec-Validated Story Generation -> Backlog -> Sprint) ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    SQLite Database                           │
│  (Products, Specs, CompiledAuthority, Epics, Stories)       │
└─────────────────────────────────────────────────────────────┘
```

### Design Patterns
- **Spec Authority Pattern**: Compiler pattern for deterministic invariants.
- **Bucket Brigade Communication**: Agents pass structured state through the orchestrator.
- **Schema-Driven Validation**: All I/O validated by Pydantic schemas.
- **Tool Context Caching**: Read-only tools support transparent caching with TTL.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- [Poetry](https://python-poetry.org/) or pip
- OpenRouter API key (for LLM access)

### Installation

```bash
# Clone the repository
git clone https://github.com/arduinitavares/project_tcc.git
cd project_tcc

# Install dependencies
pip install -e .
# or with Poetry
poetry install

# Set up environment variables
cp .env.example .env
# Edit .env with your OPENROUTER_API_KEY
```

### Running the Application

```bash
# Start the interactive orchestrator (recommended)
python main.py

# This launches ADK Web with:
# - Session persistence via DatabaseSessionService
# - All agents and tools available
```

---

## 📖 Usage Examples

### 1. Create a New Product Vision

```
You: I want to build a recipe discovery app for home cooks

Agent: I'll help you define the product vision. Let me ask some clarifying questions:
- What should we call this product?
- What specific problem does it solve for home cooks?
...

You: Let's call it MealMuse...

Agent: Great! Vision saved. Now, do you want to define the Technical Specification?
```

### 2. Define Specification & Plan Sprint

```
You: Here is the technical spec for MealMuse... [Pastes Spec]

Agent: Spec compiled and Authority accepted. 
Ready to generate Roadmap and User Stories based on this spec.

You: Plan a sprint for MealMuse

Agent: Based on the Spec and Roadmap, here's your backlog...
```

### 3. Execute Sprint Work

```
You: Mark story 35 as done

Agent: ✅ Story #35 updated: IN_PROGRESS → DONE
"Access app on iOS and Android"
```

---

## 📁 Project Structure

```
project_tcc/
├── main.py                          # Entry point, ADK Web bootstrap
├── agile_sqlmodel.py                # Database schema (SQLModel/SQLAlchemy)
├── PLANNING_WORKFLOW.md             # Detailed workflow documentation
├── SPEC_DRIVEN_ARCHITECTURE_PLAN.md # Spec Authority Architecture
├── CLAUDE.md                        # TCC requirements and methodology
│
├── orchestrator_agent/
│   ├── agent.py                     # Root agent with all tools
│   ├── instructions.txt             # State machine routing
│   └── agent_tools/
│       ├── product_vision_tool/     # Vision gathering agent
│       ├── spec_authority_compiler_agent/ # Spec Compiler
│       ├── product_roadmap_agent/   # Roadmap planning agent
│       ├── story_pipeline/          # Spec validation pipeline
│       └── sprint_planning/         # Sprint planning & execution
│
├── tools/
│   ├── orchestrator_tools.py        # Read-only query tools
│   ├── db_tools.py                  # Database mutation tools
│   └── spec_tools.py                # Spec persistence and authority tools
│
├── utils/
│   ├── schemes.py                   # Shared Pydantic schemas
│   └── helper.py                    # Instruction loading
│
└── tests/
    ├── conftest.py                  # Test fixtures
    └── test_*.py                    # Unit tests
```

---

## 🗄️ Database Schema

```
products ─┬─> spec_registry ─> compiled_spec_authority
          │
          ├─> themes ─┬─> epics ─┬─> features
          │           │          │
          │           │          └─> user_stories ─┬─> sprint_stories
          │           │                            │
          └─> teams ──┴─> sprints ─────────────────┘
                              │
                              └─> workflow_events (metrics)
```

Key tables:
- **products**: Top-level container
- **spec_registry**: Versioned technical specifications
- **compiled_spec_authority**: Deterministic invariants compiled from specs
- **user_stories**: INVEST-ready stories with spec validation
- **sprints**: Sprint planning with goals and dates

---

## 🔧 Technology Stack

| Category | Technology |
|----------|------------|
| **Agent Framework** | [Google ADK](https://github.com/google/adk-python) (Agent Development Kit) |
| **LLM Abstraction** | LiteLLM via OpenRouter API |
| **Model** | `openrouter/google/gemini-2.0-flash-exp` (or updated model) |
| **ORM** | SQLModel (0.0.27+) + SQLAlchemy |
| **Database** | SQLite (portable, zero-config) |
| **Schema Validation** | Pydantic v2 |
| **Session Management** | ADK DatabaseSessionService |

---

## 📊 TCC Evaluation Metrics

This system is designed for academic evaluation using:

| Metric | Method | Purpose |
|--------|--------|---------|
| **Cognitive Load** | NASA-TLX questionnaire | Measure mental demand reduction |
| **Artifact Quality** | Spec compliance validation | Ensure story quality |
| **Workflow Efficiency** | Cycle time & lead time | Track planning speed |
| **Baseline Comparison** | Solo developer with traditional tools | Validate improvement |

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/

# Run with coverage (Minimum 80%)
pytest tests/ --cov=. --cov-report=html
```

---

## 🛣️ Roadmap

### ✅ Completed (v1.1)
- [x] Product Vision Agent (7-component gathering)
- [x] Specification Authority System (Compiler & Validation Gates)
- [x] Roadmap Agent (Now/Next/Later prioritization)
- [x] Story Pipeline with Spec Authority Pinning
- [x] Sprint Planning & Execution tools
- [x] WorkflowEvent metrics capture

### 🔜 Planned (v1.2)
- [ ] Automated Spec Updates via Feedback
- [ ] Task breakdown from stories
- [ ] Burndown chart visualization

### 🔮 Future
- [ ] Multi-project portfolio view
- [ ] Integration with GitHub/Jira

---

## 📚 Documentation

- [PLANNING_WORKFLOW.md](PLANNING_WORKFLOW.md) - Detailed workflow documentation
- [SPEC_DRIVEN_ARCHITECTURE_PLAN.md](SPEC_DRIVEN_ARCHITECTURE_PLAN.md) - Spec Authority Architecture details
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - AI agent coding guidelines

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Alexandre Tavares**
- GitHub: [@arduinitavares](https://github.com/arduinitavares)
