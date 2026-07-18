# PaisaEra Backend

AI-first personal finance backend for PaisaEra — India's Hinglish-speaking AI Financial Companion.

This is a **working scaffold**, not a finished production system. It boots, has real auth logic, a real database schema, and a real (provider-agnostic) AI gateway — but you need to supply your own API keys and run migrations before it's live. Everywhere a real credential is needed, it's read from environment variables (see `.env.example`) — nothing is hardcoded.

---

## Architecture

```
                        ┌───────────────────────┐
                        │   Mobile App (Expo)     │  ← see ../paisaera-mobile
                        └───────────┬───────────┘
                                    │ HTTPS
                        ┌───────────▼───────────┐
                        │   FastAPI (this repo)   │
                        └──┬──────┬───────┬──────┘
                           │      │       │
                 ┌─────────▼┐ ┌───▼───┐ ┌─▼─────────────┐
                 │PostgreSQL│ │ Redis │ │  AI Gateway     │
                 │(SQLAlchemy)│ │(cache,│ │  (LiteLLM →     │
                 │          │ │ limits)│ │  OpenAI/Gemini/ │
                 │          │ │       │ │  OpenRouter)    │
                 └──────────┘ └───────┘ └────────┬───────┘
                                                    │ tool calls
                                          ┌─────────▼─────────┐
                                          │  Financial           │
                                          │  Intelligence Engine  │
                                          │  (app/services/fie/)  │
                                          │                        │
                                          │  Categorizer           │
                                          │       ↓                │
                                          │  Budget Engine          │
                                          │       ↓                │
                                          │  Money Score Engine     │
                                          │       ↓                │
                                          │  Money DNA Engine       │
                                          │       ↓                │
                                          │  Recommendation Engine  │
                                          └────────────────────────┘
```

The FIE is deliberately DB-agnostic — routers fetch data from Postgres and hand the engine plain dataclasses, which is what makes every stage unit-testable without spinning up a database (see "Verifying the FIE" below).

**Not included yet, on purpose** (see the Implementation Plan doc's infra sequencing — these come online in later phases): Kafka, Kubernetes, Qdrant, ClickHouse. This scaffold runs on Postgres + Redis alone, which is enough for Phase 0/1.

---

## What's actually implemented

- ✅ Project structure, config loading from environment variables
- ✅ Database models: users, OTP verifications, sessions, transactions, budgets, goals, quests, streaks, financial scores, AI conversations/messages, AI usage tracking, audit log
- ✅ Mobile OTP authentication flow (send + verify), with a pluggable SMS provider interface (console-log provider included for local dev — swap in MSG91/Twilio when you have keys)
- ✅ JWT session issuance + refresh token rotation
- ✅ **Financial Intelligence Engine** (`app/services/fie/`) — the "brain," per the architecture review's top recommendation: Categorizer → Budget Engine → Money Score Engine → Money DNA Engine → Recommendation Engine, each a pure/testable module with no DB dependency of its own. Verified against real test data (see "Verifying the FIE" below), not just import-checked.
- ✅ **AI Tool Calling registry** (`app/services/ai_gateway/tools.py`) — the LLM can call `addExpense`, `updateGoal`, `calculateSavings`, `forecastCashflow`, `checkBudgetStatus` as structured function calls (OpenAI-compatible schema via LiteLLM), returning real `tool_card` data instead of the client having to regex-guess intent from response text.
- ✅ **Real multi-step AI orchestration via LangGraph** (`app/services/ai_gateway/orchestrator.py`) — chains multiple tool calls in one conversational turn (e.g. "log this expense AND tell me if I'm over budget" → `addExpense` then `checkBudgetStatus`, not just one). Hard-capped at 3 iterations so a model that never stops requesting tools can't loop forever or burn unbounded provider spend. 7 tests (`tests/test_orchestrator.py`) verify the graph's routing logic and chaining behavior with mocked LLM calls — genuinely exercises two sequential tool calls, not just imports cleanly.
- ✅ AI Gateway: personality system (6 personas, Hinglish-only prompts), topic scope pre-filter, per-user daily rate limiting via Redis, LiteLLM provider abstraction with a template-bank fallback
- ✅ Chat endpoint wired to the AI Gateway, now tool-calling-capable
- ✅ Transaction CRUD, now auto-categorized via the FIE's Categorizer stage
- ✅ Goals CRUD (`/goals`) — didn't exist in the previous pass; added to match what the mobile app's repository layer expects
- ✅ Money Score endpoint, refactored to call the FIE engine instead of duplicating calculation logic
- ✅ Money DNA endpoint (`/money-dna`) — new, backed by the FIE's classifier
- ✅ **Typed API contract via OpenAPI** (`app/schemas/api.py`) — every response schema uses a camelCase alias generator so the wire format matches the mobile TS types exactly (`target_amount` → `targetAmount`). This was verified by actually regenerating the OpenAPI spec and inspecting field names, not assumed — see "OpenAPI → TypeScript pipeline" below.
- ✅ "Future Self" affordability-check endpoint (deterministic financial calc + LLM narrative wrapper)
- ✅ Daily Brief endpoint
- ✅ Docker Compose for local dev (Postgres + Redis + API)
- ✅ Alembic migration setup (empty — run `alembic revision --autogenerate` once models are finalized)

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

49 tests, all passing as of this commit: 26 for the Financial Intelligence Engine (categorizer, budget math, Money Score, Money DNA, recommendations), 16 for the AI Gateway (scope filter, personalities, tool schemas), 7 for the LangGraph orchestrator's routing and tool-chaining logic. The orchestrator tests mock the LLM call itself (no API key needed to run the suite) but exercise the real graph — including a test that genuinely chains two sequential tool calls and one that verifies the iteration cap actually stops a model that never stops requesting tools.

## OpenAPI → TypeScript pipeline

```bash
python scripts/generate_openapi.py       # writes openapi.json
cd ../paisaera-mobile
npm run generate:types                    # or: bash scripts/generate-types.sh
```

This regenerates `paisaera-mobile/src/types/generated.ts` directly from the live FastAPI schema. Run it after any router/schema change — the mobile app's hand-written types in `src/types/index.ts` should be treated as the *intended* contract, and `generated.ts` as the *actual* one; a mismatch between them is a real bug (this is exactly how the transactions/goals response field-naming mismatch in this pass was caught and fixed, not by inspection).

## Verifying the FIE

The engine is pure functions over plain data — no DB session needed to test it:

```python
from app.services.fie.engine import fie
from app.services.fie.budget_engine import CategoryBudget

snapshot = fie.compute_snapshot(
    categories=[CategoryBudget("Khana", allocated=6000, spent=5200)],
    total_income_30d=65000, total_expense_30d=42000,
    goal_progress_ratios=[0.62], category_spend_pct={"Khana": 0.45},
    monthly_income=65000,
)
print(snapshot.money_score.total_score, snapshot.money_score.level)
```

## What's explicitly NOT implemented (you'll need to add these)

- ❌ Real SMS OTP provider integration — currently logs the OTP to console in dev mode. Swap `app/services/otp_service.py`'s `ConsoleOTPProvider` for a real MSG91/Twilio implementation.
- ❌ Real AI provider API keys — set `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` in `.env`. Without any of these, the AI Gateway automatically falls back to the static Hinglish template bank, so the API still works end-to-end for testing.
- ❌ Speech-to-text for voice entry — the mobile app should handle this client-side (as the demo artifact does via the browser's Web Speech API); this backend just receives the resulting text.
- ❌ Payment provider (for Premium/Pro plan billing) — flagged as an open item in the PaisaEra Security & Access Document; not wired here.
- ❌ Celery worker deployment config — the `app/workers/celery_app.py` file defines the app and one example scheduled task (daily brief), but you'll need to actually run `celery -A app.workers.celery_app worker` and `celery -A app.workers.celery_app beat` as separate processes/containers.

---

## Getting started

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd paisaera-backend
cp .env.example .env
```

Open `.env` and fill in what you have. At minimum, set `DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET_KEY` (generate one with `openssl rand -hex 32`). Everything else has a safe fallback for local development.

### 2. Run with Docker Compose (recommended for first run)

```bash
docker-compose up --build
```

This starts Postgres, Redis, and the API on `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### 3. Run migrations

```bash
docker-compose exec api alembic upgrade head
```

(First time: `docker-compose exec api alembic revision --autogenerate -m "initial schema"` to generate the migration from the models, then `upgrade head`.)

### 4. Run locally without Docker (alternative)

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

You'll need Postgres and Redis running separately and pointed to via `.env`.

---

## Project layout

```
app/
├── main.py                 # FastAPI app entrypoint
├── core/
│   ├── config.py            # Settings loaded from environment variables
│   ├── database.py          # SQLAlchemy engine/session setup
│   └── security.py          # JWT issuance, OTP hashing (Argon2id), rate-limit helpers
├── models/                  # SQLAlchemy ORM models (one file per domain)
├── schemas/                 # Pydantic request/response schemas
├── routers/                 # API endpoints, one file per feature area
├── services/                 # Business logic (AI gateway, OTP provider, money score, future self)
└── workers/
    └── celery_app.py        # Celery app + scheduled tasks (daily brief, score recompute)

alembic/                     # Database migrations
docker-compose.yml
Dockerfile
requirements.txt
.env.example
```

---

## Pushing to GitHub

```bash
git init
git add .
git commit -m "Initial PaisaEra backend scaffold"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

`.env` is already in `.gitignore` — never commit real API keys. `.env.example` is safe to commit (no real secrets, just variable names).

---

## Reference documents

This backend implements the architecture described in the PaisaEra document set (TRD, Backend Schemas Document, Security & Access Document). Table names match the Backend Schemas Document exactly where it specifies them (`financial_scores`, `score_history`, `xp_history`, etc.) so the two stay in sync as the product evolves.
