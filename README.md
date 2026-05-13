# Grab Collections Agent Demo

Demo repo for an AI-assisted payment collections workflow for Grab gig workers. The app is built as a two-sided demo:

- `Admin view`: portfolio summary, worker-level risk/health data, escalated cases, and manual agent triggering
- `Gig worker view`: the latest repayment message, proposed plan, earnings/health context, negotiation history, and commitment breach history

This is a demo environment, not a production app. Role switching is done inside the UI and worker selection is manual; there is no real authentication or authorization layer yet.

## What the demo currently includes

### Admin experience

- Portfolio metrics such as recovery rate, revenue at risk, escalated cases, frozen cases, and average health score
- Worker table with gig type, health score, risk tier, amount due, overdue days, and broken commitment count
- Escalation queue for workers whose cases are frozen or escalated
- Manual "Trigger agent" action that runs the agent graph and delivers a notification to the worker view

### Gig worker experience

- Latest message from the collections agent
- Repayment plan with installment dates and amounts when a plan is offered
- Actions to accept a plan, ask for a different plan, or request support
- Financial health score and component breakdown
- Last 14 days of earnings plus full earnings history
- Agent message history, negotiation history, and commitment breach history

### Agent workflow

- Reads overdue payment state, earnings patterns, and financial health
- Classifies risk into `low`, `medium`, `high`, or `hardship`
- Generates a repayment plan aligned to earnings windows
- Drafts an empathetic worker-facing message
- Handles worker responses:
  - `accepted` -> move case into active negotiation
  - `rejected` -> generate a counter-offer
  - `support_requested` -> escalate to human review
- Freezes autonomous restructuring after repeated broken commitments and generates an escalation summary for admin/support

## Repo structure

```text
agent/   LangGraph flow, node logic, health scoring, and tools
api/     FastAPI backend and request/response models
data/    Synthetic data generator for demo personas
db/      SQLModel database models and session setup
ui/      Streamlit admin + worker demo interface
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Then configure `.env`:

- Set `GEMINI_API_KEY` to use Gemini for agent messages and escalation summaries, or
- Set `USE_MOCK_LLM=true` for a fully offline demo flow

Key config values:

- `DATABASE_URL=sqlite:///./grab_collections.db`
- `COMMITMENT_FREEZE_THRESHOLD=2`
- `API_URL` for the Streamlit app defaults to `http://localhost:8000`

## Seed demo data

```powershell
.\.venv\Scripts\python.exe data/generate_synthetic_data.py
```

The generator creates:

- 10 synthetic workers
- 60 days of earnings per worker
- overdue payment records
- seeded financial health scores
- historical accepted-plan breaches for selected personas

## Run the app

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

Frontend:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

Open the Streamlit app and choose either `Admin dashboard` or `Worker view`.

## Demo personas

These seeded workers are the easiest ones to use in a walkthrough:

1. `GW001` - Siti Noor
   Low-risk, steady earner. Good for the basic trigger -> offer -> accept flow.

2. `GW002` - Ahmad Razali
   Medium-risk, more volatile income. Good for trigger -> reject -> counter-offer -> accept.

3. `GW003` - Priya Pillai
   Hardship profile with a recent income drop. Good for showing softer messaging and more flexible repayment logic.

4. `GW004` - Budi Santoso
   Has one prior broken commitment. Good for showing how another missed payment moves the worker closer to a freeze.

5. `GW006` - Ravi Kumar
   Already has two broken commitments and starts in a frozen/escalated state. Good for showing the escalation queue immediately.

## Main API endpoints

### Core agent actions

- `POST /trigger-agent` -> runs the graph and returns the agent response
- `POST /notifications/send` -> runs the graph and stores/delivers a worker notification
- `POST /user-response` -> handles response against a saved agent state
- `POST /worker/notification-response` -> worker-facing accept/reject/support action
- `POST /mark-payment-missed` -> records a missed installment and freezes restructuring after threshold

### Admin and worker data

- `GET /users` -> worker list for admin view
- `GET /dashboard` -> admin summary metrics and escalation queue
- `GET /worker/{user_id}/overview` -> worker profile, payment, health, earnings, notifications, negotiations, breaches
- `GET /worker/{user_id}/notifications` -> worker notifications only
- `GET /user/{user_id}/history` -> negotiations and commitment breaches
- `GET /user/{user_id}/health-score` -> financial health details

Example calls:

```powershell
curl -X POST http://localhost:8000/notifications/send `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"GW001\"}"

curl http://localhost:8000/dashboard
curl http://localhost:8000/worker/GW001/overview
```

## Notes and current limitations

- The app has separate admin and worker views, but access control is demo-only today
- Worker identity is selected from a dropdown in the UI
- Notifications are persisted in SQLite and shown in the worker view; there is no real push channel
- The `agent/memory.py` helper exists, but the current UI/API flow relies on database-backed notifications, negotiations, and agent session state
- All currency is shown in SGD
- Payment scheduling and seeded demo data use `Asia/Singapore`
