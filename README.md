# GrabHack 2.0 - AI Collections Agent

Prototype AI collections agent for Grab gig workers. It detects overdue payments, analyzes earnings patterns, scores financial health, proposes repayment plans, tracks broken accepted commitments, and escalates frozen cases with an AI-written support briefing.

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
# Fill GEMINI_API_KEY for real LLM testing, or set USE_MOCK_LLM=true for offline demo mode.
```

## Seed Synthetic Data

```bash
.\.venv\Scripts\python.exe data/generate_synthetic_data.py
```

## Run

Terminal 1:

```bash
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

Terminal 2:

```bash
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

## Demo Personas

1. Happy path: Siti Noor, `GW001`  
   Run agent, accept the plan, and show the confirmed payment plan.

2. Negotiation loop: Ahmad Razali, `GW002`  
   Run agent, reject the first plan, show the counter-offer, then accept.

3. Hardship detection: Priya Pillai, `GW003`  
   Run agent and show the automatic grace period caused by the recent income drop.

4. Broken commitment freeze: Ravi Kumar, `GW006`  
   Run agent and show automatic escalation because the case is already frozen after 2 broken commitments. Then use Budi Santoso, `GW004`, accept or use the historical breach state, simulate a missed installment after an accepted plan, rerun the agent, and show the freeze/escalation flow.

## Useful API Calls

```bash
curl -X POST http://localhost:8000/trigger-agent ^
  -H "Content-Type: application/json" ^
  -d "{\"user_id\":\"GW001\"}"

curl http://localhost:8000/dashboard
curl http://localhost:8000/user/GW006/history
```

All amounts are in SGD and all scheduling uses Asia/Singapore time.
