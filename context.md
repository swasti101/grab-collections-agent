# Project Context: Grab Collections Agent

> **How to use this file**: Paste this into any new LLM session to restore full project context. Update the sections marked 🔄 as the project evolves.

---

## What this project is

An AI-assisted payment collections workflow for Grab gig workers. It is a **demo app** (not production) with two sides:

- **Admin view** — portfolio metrics, worker risk/health data, escalation queue, manual agent triggering
- **Gig worker view** — repayment messages, proposed plans, earnings context, negotiation and breach history

---

## Tech stack

| Layer         | Technology                                                  |
| ------------- | ----------------------------------------------------------- |
| Agent         | LangGraph (flow, nodes, health scoring, tools)              |
| Backend       | FastAPI + SQLModel                                          |
| Database      | SQLite (`grab_collections.db`)                              |
| Frontend      | Streamlit                                                   |
| LLM           | Gemini (via `GEMINI_API_KEY`) or mock (`USE_MOCK_LLM=true`) |
| Currency / TZ | SGD / Asia/Singapore                                        |

---

## Repo structure

```
agent/   LangGraph flow, node logic, health scoring, tools
api/     FastAPI backend, request/response models
data/    Synthetic data generator
db/      SQLModel models, session setup
ui/      Streamlit admin + worker interface
```

---

## Agent workflow (core logic)

1. Reads overdue payment state, earnings patterns, financial health
2. Classifies risk → `low` | `medium` | `high` | `hardship`
3. Generates a repayment plan aligned to earnings windows
4. Drafts an empathetic worker-facing message
5. Handles worker responses:
   - `accepted` → move to active negotiation
   - `rejected` → generate counter-offer
   - `support_requested` → escalate to human review
6. After repeated broken commitments (threshold: 2), freezes autonomous restructuring and generates escalation summary

---

## Key configuration (`.env`)

```
GEMINI_API_KEY=...
USE_MOCK_LLM=true              # set true for fully offline demo
DATABASE_URL=sqlite:///./grab_collections.db
COMMITMENT_FREEZE_THRESHOLD=2
API_URL=http://localhost:8000  # used by Streamlit
```

---

## Running the app

```powershell
# Setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env

# Seed data
.\.venv\Scripts\python.exe data/generate_synthetic_data.py

# Backend
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000

# Frontend
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

---

## Seeded demo personas

| ID    | Name         | Profile                      | Best for demoing                    |
| ----- | ------------ | ---------------------------- | ----------------------------------- |
| GW001 | Siti Noor    | Low-risk, steady earner      | Basic trigger → offer → accept      |
| GW002 | Ahmad Razali | Medium-risk, volatile income | Trigger → reject → counter → accept |
| GW003 | Priya Pillai | Hardship, recent income drop | Soft messaging, flexible repayment  |
| GW004 | Budi Santoso | 1 prior broken commitment    | Approaching freeze threshold        |
| GW006 | Ravi Kumar   | 2 broken commitments, frozen | Escalation queue demo               |

---

## Key API endpoints

### Agent actions

| Method | Endpoint                        | Purpose                                           |
| ------ | ------------------------------- | ------------------------------------------------- |
| POST   | `/trigger-agent`                | Run graph, return agent response                  |
| POST   | `/notifications/send`           | Run graph, store + deliver worker notification    |
| POST   | `/user-response`                | Handle response against saved agent state         |
| POST   | `/worker/notification-response` | Worker accept / reject / support action           |
| POST   | `/mark-payment-missed`          | Record missed installment; freeze after threshold |

### Data reads

| Method | Endpoint                          | Purpose                                  |
| ------ | --------------------------------- | ---------------------------------------- |
| GET    | `/users`                          | Worker list for admin                    |
| GET    | `/dashboard`                      | Admin summary metrics + escalation queue |
| GET    | `/worker/{user_id}/overview`      | Full worker profile                      |
| GET    | `/worker/{user_id}/notifications` | Worker notifications                     |
| GET    | `/user/{user_id}/history`         | Negotiations + commitment breaches       |
| GET    | `/user/{user_id}/health-score`    | Financial health details                 |

---

## Known limitations / current state

- No real auth — role switching and worker selection are UI-only
- No real push notifications — stored in SQLite, shown in worker view
- `agent/memory.py` exists but current flow uses DB-backed state (notifications, negotiations, agent sessions)
- All amounts in SGD

---

## 🔄 Active work / decisions (update each session)

> Add notes here as the project progresses. Examples:

- [ ] What you're currently building or fixing
- [ ] Architectural decisions made this session
- [ ] Open questions or blockers
- [ ] Next steps

---

## 🔄 Session log (append, don't overwrite)

> One line per session. Helps LLMs understand project history.

| Date | What happened                            |
| ---- | ---------------------------------------- |
| —    | Initial context file created from README |
