# 🤖 Autonomous Agile Management Platform

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Google ADK](https://img.shields.io/badge/Google-ADK-orange.svg)](https://github.com/google/adk-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **A multi-agent AI system that simulates Scrum roles to reduce cognitive load for small development teams (1-4 developers).**

This project is part of a **TCC (Trabalho de Conclusão de Curso)** research initiative exploring how AI agents can autonomously orchestrate Agile workflows, from product vision to sprint execution.

---

## ✨ Features

### 🎯 Complete Agile Workflow Pipeline
```
Vision → Roadmap → Features → User Stories → Sprint Planning → Execution
```

### 🧠 Intelligent Agents
| Agent | Role | Capabilities |
|-------|------|--------------|
| **Product Vision Agent** | Product Owner | Guides users through 7-component vision creation via multi-turn conversation |
| **Roadmap Agent** | Product Owner | Converts vision into prioritized themes with Now/Next/Later timeframes |
| **Story Pipeline** | Developer Support | Generates INVEST-compliant user stories with validation |
| **Sprint Planning** | Scrum Master | Plans sprints with capacity modeling and team auto-creation |
| **Sprint Execution** | Scrum Master | Tracks progress, status updates, and velocity metrics |

### 🛠️ Key Capabilities
- **Draft → Review → Commit Pattern**: All artifacts go through validation before persistence
- **Stateless Agents**: Predictable behavior with state injection via JSON
- **Incremental Refinement**: Never loses previous work during multi-turn conversations
- **Idempotent Operations**: Safe to retry without creating duplicates
- **WorkflowEvent Metrics**: Built-in tracking for TCC evaluation (NASA-TLX, cycle time)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                        │
│         (State Machine with 18 States + Routing)            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Vision    │  │   Roadmap   │  │   Story Pipeline    │  │
│  │   Agent     │  │   Agent     │  │ (Draft→Validate→    │  │
│  │             │  │             │  │  Refine)            │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Sprint Planning & Execution                 ││
│  │  (9 tools: planning, query, status, modify, complete)   ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    SQLite Database                           │
│  (Products, Themes, Epics, Features, Stories, Sprints)      │
└─────────────────────────────────────────────────────────────┘
```

### Design Patterns
- **Bucket Brigade Communication**: Agents pass structured state through the orchestrator
- **Schema-Driven Validation**: All I/O validated by Pydantic schemas
- **Tool Context Caching**: Read-only tools support transparent caching with TTL
- **Multi-Agent via AgentTool**: Child agents wrapped as tools in parent's toolset

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
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
# - Pre-loaded project state
```

The web interface will open at `http://localhost:8000`

---

## 📖 Usage Examples

### 1. Create a New Product Vision

```
You: I want to build a recipe discovery app for home cooks

Agent: I'll help you define the product vision. Let me ask some clarifying questions:
- What should we call this product?
- What specific problem does it solve for home cooks?
- Who are the main competitors?
...

You: Let's call it MealMuse. The problem is that people waste time searching...

Agent: Great! Here's your vision statement:
"For home cooks who struggle to find recipes matching their ingredients,
MealMuse is a mobile app that suggests personalized recipes.
Unlike AllRecipes and Tasty, our product uses AI to match what's in your fridge."

Would you like to save this vision?
```

### 2. Plan a Sprint

```
You: Plan a sprint for MealMuse

Agent: Here's your backlog (5 stories, 0 points):
- Story #35: Access app on iOS and Android
- Story #37: Search recipes by ingredient
...

What's your sprint goal and which stories should we include?

You: Goal is "Deliver MVP for recipe discovery". Include stories 35, 37, 38, 39, 43

Agent: ✅ Sprint Draft for Team MealMuse
Goal: Deliver MVP for recipe discovery
Duration: 2026-01-17 → 2026-01-31 (14 days)
Stories: 5 selected

Would you like to save this sprint?
```

### 3. Execute Sprint Work

```
You: Mark story 35 as done

Agent: ✅ Story #35 updated: IN_PROGRESS → DONE
"Access app on iOS and Android"

You: Complete the sprint

Agent: 🏁 Sprint #1 completed!
- 4/5 stories done (80.0%)
- Velocity: 10 points
- 1 incomplete story returned to backlog
```

---

## 📁 Project Structure

```
project_tcc/
├── main.py                          # Entry point, ADK Web bootstrap
├── agile_sqlmodel.py                # Database schema (SQLModel/SQLAlchemy)
├── PLANNING_WORKFLOW.md             # Detailed workflow documentation
├── CLAUDE.md                        # TCC requirements and methodology
│
├── orchestrator_agent/
│   ├── agent.py                     # Root agent with all tools
│   ├── instructions.txt             # State machine routing (18 states)
│   └── agent_tools/
│       ├── product_vision_tool/     # Vision gathering agent
│       ├── product_roadmap_agent/   # Roadmap planning agent
│       ├── product_user_story_tool/ # Story generation
│       ├── story_pipeline/          # INVEST validation pipeline
│       └── sprint_planning/         # Sprint planning & execution
│           ├── tools.py             # Planning tools (706 lines)
│           ├── sprint_query_tools.py
│           └── sprint_execution_tools.py
│
├── tools/
│   ├── orchestrator_tools.py        # Read-only query tools
│   └── db_tools.py                  # Database mutation tools
│
├── utils/
│   ├── schemes.py                   # Shared Pydantic schemas
│   ├── response_parser.py           # JSON validation utilities
│   └── helper.py                    # Instruction loading
│
└── tests/
    ├── conftest.py                  # Test fixtures
    └── test_*.py                    # Unit tests
```

---

## 🗄️ Database Schema

```
products ─┬─> themes ─┬─> epics ─┬─> features
          │           │          │
          │           │          └─> user_stories ─┬─> sprint_stories
          │           │                            │
          └─> teams ──┴─> sprints ─────────────────┘
                              │
                              └─> workflow_events (metrics)
```

Key tables:
- **products**: Top-level container with vision and roadmap
- **themes/epics/features**: Hierarchical product structure
- **user_stories**: INVEST-compliant stories with status tracking
- **sprints**: Sprint planning with goals and dates
- **workflow_events**: Metrics for TCC evaluation

---

## 🔧 Technology Stack

| Category | Technology |
|----------|------------|
| **Agent Framework** | [Google ADK](https://github.com/google/adk-python) (Agent Development Kit) |
| **LLM Abstraction** | LiteLLM via OpenRouter API |
| **Model** | `openrouter/google/gemini-2.5-pro` |
| **ORM** | SQLModel + SQLAlchemy |
| **Database** | SQLite (portable, zero-config) |
| **Schema Validation** | Pydantic v2 |
| **Session Management** | ADK DatabaseSessionService |

---

## 📊 TCC Evaluation Metrics

This system is designed for academic evaluation using:

| Metric | Method | Purpose |
|--------|--------|---------|
| **Cognitive Load** | NASA-TLX questionnaire | Measure mental demand reduction |
| **Artifact Quality** | INVEST criteria validation | Ensure story quality |
| **Workflow Efficiency** | Cycle time & lead time | Track planning speed |
| **Baseline Comparison** | Solo developer with traditional tools | Validate improvement |

WorkflowEvents automatically capture:
- `duration_seconds`: Time spent on each planning phase
- `turn_count`: Conversation turns to complete tasks
- `event_metadata`: Contextual data for analysis

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_orchestrator_tools.py -v
```

---

## 🛣️ Roadmap

### ✅ Completed (v1.0)
- [x] Product Vision Agent (7-component gathering)
- [x] Roadmap Agent (Now/Next/Later prioritization)
- [x] Database structure creation (Theme → Epic → Feature)
- [x] Story Pipeline with INVEST validation
- [x] Sprint Planning MVP (9 tools)
- [x] Sprint Execution (status, modify, complete)
- [x] WorkflowEvent metrics capture

### 🔜 Planned (v1.1)
- [ ] Daily Standup automation
- [ ] Sprint Review/Retrospective flows
- [ ] Burndown chart visualization
- [ ] Task breakdown from stories
- [ ] Team member management
- [ ] Definition of Done (DoD) tracking

### 🔮 Future
- [ ] Multi-project portfolio view
- [ ] Integration with GitHub/Jira
- [ ] Voice interface support
- [ ] Mobile companion app

---

## 📚 Documentation

- [PLANNING_WORKFLOW.md](PLANNING_WORKFLOW.md) - Detailed workflow documentation
- [CLAUDE.md](CLAUDE.md) - TCC requirements and research methodology
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - AI agent coding guidelines

---

## 🤝 Contributing

Contributions are welcome! This is an academic project, but improvements are appreciated.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please follow the existing code patterns documented in `.github/copilot-instructions.md`.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Alexandre Tavares**
- GitHub: [@arduinitavares](https://github.com/arduinitavares)

---

## 🙏 Acknowledgments

- [Google ADK](https://github.com/google/adk-python) for the agent framework
- [OpenRouter](https://openrouter.ai/) for LLM API access
- Academic advisors and TCC committee

---

<p align="center">
  <i>Built with ❤️ for reducing cognitive load in Agile teams</i>
</p>
