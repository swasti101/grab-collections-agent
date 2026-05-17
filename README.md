# Grab Collections Agent Demo

Demo repo for an AI-assisted collections workflow for Grab gig workers. The app is intentionally built as a two-sided demo:

- `Admin dashboard`: portfolio view, escalations, drift scan, trigger-agent preview, and explicit send approval
- `Gig worker view`: notification card / popup-style message surface, repayment plan, financial health, earnings context, and negotiation history

This is a demo environment, not a production app. Role switching is manual inside the UI and there is no real authentication layer yet.

## What The Demo Shows

### Admin experience

- Portfolio metrics: recovery rate, revenue at risk, escalated cases, frozen cases, average health score
- Worker table with gig type, health score, risk tier, amount due, overdue days, and broken commitments
- `Trigger agent` flow that runs the LangGraph collections agent in preview mode first
- Live trace view showing what the agent is analyzing, which tools are being called, and what each step produced
- `Drift scanner` that analyzes the full worker base for early default-pattern drift
- Explicit review-before-send flow for both collections notifications and proactive check-ins
- Escalation queue for frozen and escalated cases

### Gig worker experience

- Notification card / popup-style surface for the latest message from Grab
- Two distinct message types:
  - `Collections notification`
  - `Proactive support check-in`
- Repayment plan details when the collections agent proposes restructuring
- Actions to accept, reject / ask for a different plan, or request support
- Financial health breakdown
- Recent and full earnings history
- Negotiation and commitment breach history

## Current Architecture

```text
Streamlit Admin UI
  -> preview stream endpoints on FastAPI
  -> explicit send endpoints on FastAPI

FastAPI
  -> LangGraph collections flow
  -> drift scoring engine
  -> Bedrock runtime model factory
  -> SQLModel persistence layer

LangGraph / Drift Engine
  -> earnings analysis
  -> risk classification
  -> repayment plan generation
  -> collections message drafting
  -> drift scoring + proactive check-in drafting

SQLite
  -> payments
  -> earnings
  -> financial health scores
  -> negotiations
  -> commitment breaches
  -> worker notifications
  -> saved agent session state
```

### LLM runtime

- Live LLM calls use AWS Bedrock only
- The shared model abstraction lives in `agent/model_factory.py`
- The runtime path uses direct `boto3.client(...).invoke_model(...)`
- Current default model IDs are:
  - `BEDROCK_REASONING_MODEL=deepseek.v3.2`
  - `BEDROCK_FAST_MODEL=deepseek.v3.2`

## Current Project Structure

```text
agent/
  drift.py            Drift scoring, proactive check-in drafting, scan traces
  graph.py            LangGraph graph definition and routing
  health_score.py     Financial health computation
  memory.py           Legacy helper; current app mostly uses DB-backed state
  model_factory.py    Shared Bedrock runtime client + model abstraction
  nodes.py            LangGraph node implementations
  state.py            Typed graph state
  tools.py            Tool functions used by the agent nodes
  trace.py            LangGraph preview/stream trace shaping for the admin UI

api/
  main.py             FastAPI routes, preview/send flows, worker/admin APIs
  models.py           Request/response models

db/
  database.py         SQLModel tables, engine, sessions

data/
  generate_synthetic_data.py   Seed workers, payments, earnings, breaches

ui/
  app.py              Streamlit admin + worker demo

requirements.txt      Python dependencies
.env.example          Example runtime configuration
grab_collections.db   SQLite database created by the app
```

## Collections Agent Flow

The current admin `Trigger agent` path is review-first.

### Step-by-step flow

1. Admin selects a worker in the `Trigger agent` tab.
2. Admin clicks `Run preview`.
3. Streamlit calls `POST /agent-preview/stream`.
4. FastAPI starts the LangGraph run and streams node-by-node progress back to the UI.
5. Admin sees a live arrow flow such as:

```text
Analyze worker income patterns and financial health
  -> Check commitment freeze
  -> Classify repayment risk score
  -> Generate repayment plan
  -> Draft worker notification message
```

6. The UI shows, for each step:
   - what is being analyzed
   - which tools were called
   - what result was produced
7. The final collections notification is shown in a review card.
8. Nothing is sent yet.
9. Admin clicks `Send to worker`.
10. Streamlit calls `POST /notifications/send-previewed`.
11. FastAPI persists the notification in `worker_notifications`.
12. The worker sees the notification card in the worker view.

### Tools called in the collections path

The collections flow currently uses these tool / model calls:

- `analyze_earning_windows`
- `calculate_financial_health_score`
- `schedule_nudge`
- `classify_risk`
- `generate_repayment_plan`
- `bedrock.invoke_model` for drafting the worker-facing message

If the case must be escalated, the graph instead drafts a support-facing escalation summary through Bedrock.

## Drift Scanner Flow

The current admin `Drift scanner` path is also review-first.

### What drift scan is trying to predict

The scanner tries to detect workers whose recent earning behavior is drifting toward patterns seen in workers who later defaulted or broke commitments, before another missed payment happens.

### Step-by-step flow

1. Admin opens the `Drift scanner` tab.
2. Admin clicks `Run drift scanner`.
3. Streamlit calls `GET /drift-scan/stream`.
4. FastAPI streams portfolio-wide progress back to the UI.
5. Admin sees a live arrow flow such as:

```text
Load worker portfolio for income analysis
  -> Establish reference default patterns
  -> Analyze drift across the portfolio
  -> Draft proactive check-ins
```

6. The UI also shows worker-by-worker progress like:
   - `Analyzing recent earning behaviour for GW003`
   - drift score updates as the scan completes
7. For each flagged worker, the UI shows:
   - drift score
   - timing drift
   - active-day consistency drop
   - weekday-pattern correlation
   - similarity to historical default patterns
   - proactive message preview
8. Nothing is sent yet.
9. Admin clicks `Send check-in`.
10. Streamlit calls `POST /notifications/send-proactive-checkin`.
11. FastAPI stores a proactive worker notification.
12. The worker sees a support-first check-in card that looks different from a collections message.

### Analysis used in drift scan

The drift engine currently uses:

- worker payment record lookup
- earnings history lookup
- timing shift detection
- activity consistency monitoring
- weekday pattern correlation
- historical similarity matching against prior defaulters / broken-commitment workers
- `bedrock.invoke_model` to draft the proactive check-in

## Worker Notification And Negotiation Flow

### Collections notification path

1. Worker opens the worker view.
2. The latest notification appears in the notification card / popup-style surface.
3. If it is a collections message, the worker can:
   - `Accept plan`
   - `Suggest different plan`
   - `Talk to support`
4. Streamlit calls `POST /worker/notification-response`.
5. FastAPI loads the saved agent state and continues the negotiation.

If the worker rejects the plan:

```text
node_handle_response
  -> node_classify_risk
  -> node_generate_plan
  -> node_draft_message
```

That produces a counter-offer and a new message.

### Proactive check-in path

If the worker receives a proactive support check-in, the actions are different:

- `I'm okay`
- `Talk through options early`
- `Talk to support`

These do not go through the collections negotiation graph. They update the proactive notification status directly.

## Main API Endpoints

### Preview and send flows

- `POST /agent-preview`
- `POST /agent-preview/stream`
- `POST /notifications/send-previewed`
- `GET /drift-scan`
- `GET /drift-scan/stream`
- `POST /notifications/send-proactive-checkin`

### Core agent actions

- `POST /trigger-agent`
- `POST /notifications/send`
- `POST /user-response`
- `POST /worker/notification-response`
- `POST /mark-payment-missed`

### Admin and worker data

- `GET /users`
- `GET /dashboard`
- `GET /worker/{user_id}/overview`
- `GET /worker/{user_id}/notifications`
- `GET /user/{user_id}/history`
- `GET /user/{user_id}/health-score`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Then configure `.env`:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN`
- `AWS_DEFAULT_REGION` or `BEDROCK_REGION`
- `BEDROCK_REASONING_MODEL=deepseek.v3.2`
- `BEDROCK_FAST_MODEL=deepseek.v3.2`
- `DATABASE_URL=sqlite:///./grab_collections.db`
- `COMMITMENT_FREEZE_THRESHOLD=2`
- `API_URL=http://localhost:8000`
- `USE_MOCK_LLM=false`

Set `USE_MOCK_LLM=true` only if you want a fully offline demo flow.

## Seed Demo Data

```powershell
.\.venv\Scripts\python.exe data/generate_synthetic_data.py
```

The generator creates:

- 10 synthetic workers
- 60 days of earnings per worker
- overdue payment records
- financial health scores
- seeded accepted-plan breaches for selected personas

## Run The App

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

Frontend:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

Then open the Streamlit app and choose either `Admin dashboard` or `Worker view`.

## Demo Personas

1. `GW001` - Siti Noor
   Low-risk, steady earner. Best for the basic trigger-agent preview -> send -> accept flow.

2. `GW002` - Ahmad Razali
   Medium-risk, more volatile income. Good for trigger-agent preview -> send -> reject -> counter-offer.

3. `GW003` - Priya Pillai
   Hardship profile with a recent income drop. Good for softer collections language and drift detection / proactive outreach.

4. `GW004` - Budi Santoso
   Has one prior broken commitment. Good for showing the path toward a freeze.

5. `GW006` - Ravi Kumar
   Already has two broken commitments and starts frozen / escalated. Good for the escalation queue story.

## Notes And Current Limitations

- The app is still demo-only; there is no real auth layer
- Worker identity is selected manually in the UI
- The worker notification surface is an in-app card / popup-style surface, not a real push notification system
- Notifications, negotiations, breaches, and agent session state are persisted in SQLite
- `agent/memory.py` exists, but the current flow is mostly DB-backed rather than memory-backed
- Live LLM calls use Bedrock runtime through the shared model factory
- All currency is shown in SGD
- Payment scheduling and seeded data use `Asia/Singapore`
