# PaisaEra — System Architecture

**Version:** 1.0
**Scope:** an AI-powered personal financial intelligence assistant. No banking, payments, UPI, or investment infrastructure — see Implementation Plan Document v2.0 for the permanent scope decision this architecture is built around.

Everything in this document reflects code that has actually been built and verified (49 passing backend tests, `tsc`/ESLint clean on mobile, a real Metro bundle export succeeding) — not a target-state aspiration. Where something is designed but not yet built, it's labeled as such explicitly.

---

## 1. Overall Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  MOBILE APP (Expo / React Native, SDK 57)                              │
│                                                                          │
│  ┌────────────┐   ┌──────────────┐   ┌───────────────┐                │
│  │ SMS Reader  │   │  UI Screens   │   │  Voice Input   │               │
│  │ (Android    │   │  (Home, Chat, │   │  (Web Speech / │               │
│  │  permission)│   │  Insights,    │   │  native STT)   │               │
│  │             │   │  Profile)     │   │                │               │
│  └──────┬─────┘   └───────┬──────┘   └───────┬────────┘               │
│         │                  │                    │                       │
│         ▼                  ▼                    ▼                       │
│  ┌─────────────────────────────────────────────────────┐              │
│  │  SMS Parser (on-device, regex-based)                   │              │
│  │  Repository Layer (Expense/Goal/Chat)                  │              │
│  │  Zustand Stores (auth/user/budget/expense/goal/chat/   │              │
│  │  settings) + TanStack Query (server state/caching)     │              │
│  │  Offline Queue (MMKV) + Sync Manager (NetInfo)          │              │
│  └───────────────────────┬───────────────────────────────┘              │
└──────────────────────────┼──────────────────────────────────────────┘
                            │ HTTPS (Axios, JWT in SecureStore)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI, Python)                                             │
│                                                                          │
│  ┌──────────┐  ┌───────────────────────────────────────────────┐     │
│  │  Auth      │  │  AI Gateway                                     │     │
│  │  (OTP,     │  │  ┌─────────────┐  ┌──────────────────────┐    │     │
│  │  JWT)      │  │  │ Scope filter │  │ LangGraph Orchestrator │   │     │
│  │            │  │  │ + rate limit │─▶│ (multi-step tool       │   │     │
│  └──────────┘  │  └─────────────┘  │  chaining, capped at 3) │   │     │
│                 │                     └───────────┬────────────┘    │     │
│                 │                                  │                  │     │
│                 │                     ┌────────────▼────────────┐    │     │
│                 │                     │  LiteLLM (provider        │    │     │
│                 │                     │  abstraction: OpenAI/      │    │     │
│                 │                     │  Gemini/OpenRouter)        │    │     │
│                 │                     └────────────────────────────┘    │     │
│                 └───────────────────────────┬───────────────────────┘     │
│                                              │ tool calls                   │
│                                              ▼                              │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │  Financial Intelligence Engine (FIE) — pure, DB-agnostic          │      │
│  │  Categorizer → Budget Engine → Money Score Engine →                │      │
│  │  Money DNA Engine → Recommendation Engine                          │      │
│  └────────────────────────────┬───────────────────────────────────┘      │
│                                 │                                          │
│  ┌──────────────────────────────▼─────────────────────────────────┐      │
│  │  PostgreSQL — users, transactions, budgets, goals, quests,        │      │
│  │  financial_scores, score_history, ai_conversations, audit_log     │      │
│  └────────────────────────────────────────────────────────────────┘      │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐      │
│  │  Redis         │  │  Celery       │  │  Structured logging      │      │
│  │  (rate limits, │  │  (scheduled   │  │  (request-ID tracing,    │      │
│  │  OTP throttle) │  │  jobs — not   │  │  built, not yet shipped  │      │
│  │                │  │  yet deployed │  │  to a log aggregator)    │      │
│  │                │  │  as a worker) │  │                          │      │
│  └──────────────┘  └──────────────┘  └────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  External: AI Provider APIs │
              │  (OpenAI / Gemini /          │
              │   OpenRouter — bring your    │
              │   own key, see               │
              │   API_REQUIREMENTS.md)       │
              └───────────────────────────┘
```

**What's deliberately absent from this diagram:** any bank/UPI/payment-processor connection for data ingestion, any money-movement path, any AA/NBFC integration. Transaction data enters the system through exactly two doors — on-device SMS parsing and manual/voice entry — both terminating at the same `POST /transactions` endpoint.

---

## 2. Backend Technology Stack

| Layer | Choice | Status |
|---|---|---|
| Web framework | FastAPI (Python 3.12) | ✅ Built |
| ORM | SQLAlchemy 2.0 | ✅ Built |
| Database | PostgreSQL | ✅ Schema built, migrations via Alembic |
| Cache / rate limiting | Redis | ✅ Built (AI Gateway limits, OTP throttle) |
| Async jobs | Celery | ✅ Code exists (`app/workers/celery_app.py`), **not yet running as a deployed worker process** |
| AI provider abstraction | LiteLLM | ✅ Built |
| AI orchestration | LangGraph | ✅ Built — verified with real (mocked-LLM) tests exercising actual multi-step tool chaining |
| Auth | JWT (python-jose) + Argon2id password/OTP hashing | ✅ Built |
| Testing | pytest + pytest-asyncio | ✅ 49 tests passing |
| Logging | Python stdlib `logging` + request-ID middleware | ✅ Built |
| Error tracking | Sentry | ⬜ Installed as a dependency target, not yet wired with a DSN |

---

## 3. Database Schema

Full field-level detail lives in the Backend Schemas Document — this is the relationship overview.

```
users ──┬──< transactions
        ├──< budgets ──< budget_categories
        ├──< goals
        ├──< quests
        ├──1 streaks
        ├──1 financial_scores ──< score_history
        │                     └──< score_events
        ├──< ai_conversations ──< ai_messages
        ├──< ai_usage_daily
        ├──1 notification_preferences
        ├──1 subscriptions (Pro plan billing — see scope note in Backend Schemas Document §9)
        └──< audit_log

otp_verifications  (mobile_number-keyed, not FK'd to users — a number
                     may attempt OTP before an account exists)
sessions ──> users  (device-scoped JWT refresh-token records)
```

**Notably absent, permanently:** `linked_accounts`, `advances`, `cards` — these existed in earlier planning as forward-compatible reference schemas and have been formally struck from the roadmap (Implementation Plan Document v2.0 §2), not merely unbuilt.

---

## 4. Authentication Flow

```
Mobile App                      Backend                        SMS Provider
    │                              │                                 │
    │  POST /auth/otp/request      │                                 │
    │  { mobile_number }           │                                 │
    ├─────────────────────────────▶│                                 │
    │                              │  Check rate limit                │
    │                              │  (5/hour, Redis-backed)           │
    │                              │  Generate 6-digit OTP             │
    │                              │  Hash (Argon2id), store           │
    │                              │  with 5-min expiry                │
    │                              ├────────────────────────────────▶│
    │                              │         Send SMS                  │
    │  { message: "OTP sent" }     │                                 │
    │◀─────────────────────────────┤                                 │
    │                              │                                 │
    │  POST /auth/otp/verify       │                                 │
    │  { mobile_number, code }     │                                 │
    ├─────────────────────────────▶│                                 │
    │                              │  Verify hash match,               │
    │                              │  check expiry, check              │
    │                              │  attempt count (max 5)            │
    │                              │  Find-or-create user               │
    │                              │  Issue access + refresh JWT        │
    │                              │  Store session (device-scoped)     │
    │  { access_token,              │                                 │
    │    refresh_token,             │                                 │
    │    is_new_user }              │                                 │
    │◀─────────────────────────────┤                                 │
    │                              │                                 │
    │  Store tokens in              │                                 │
    │  expo-secure-store             │                                 │
    │  (never MMKV/AsyncStorage)     │                                 │
    │                              │                                 │
    │  Every subsequent request:     │                                 │
    │  Authorization: Bearer <token> │                                 │
    ├─────────────────────────────▶│  Decode JWT, load user            │
    │                              │  (app/core/deps.py)                │
```

**Google Sign-In** exists as a secondary method in the PRD's spec but is not yet implemented in this codebase — OTP is the only working auth path currently.

**Session revocation** (`POST /users/me/sessions/revoke-others`) is real and tested — marks every session row except the current one as revoked.

---

## 5. API Contracts

Generated directly from the live FastAPI app (`scripts/generate_openapi.py` → `openapi-typescript` → `src/types/generated.ts` on mobile) — this table is the actual current surface, not a plan:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/otp/request` | Send OTP |
| POST | `/api/v1/auth/otp/verify` | Verify OTP, issue JWT |
| GET | `/api/v1/chat/personalities` | List the 6 AI personalities |
| POST | `/api/v1/chat/message` | Send a chat message — routes through AI Gateway + LangGraph orchestrator |
| GET | `/api/v1/transactions` | List user's transactions |
| POST | `/api/v1/transactions` | Create a transaction (manual, quick-add, or SMS-parsed) |
| POST | `/api/v1/transactions/voice-entry` | Parse a voice transcript into a transaction |
| POST | `/api/v1/transactions/sms-parse` | Documents the client-side SMS contract (501 — real parsing happens on-device) |
| GET | `/api/v1/goals` | List goals |
| POST | `/api/v1/goals` | Create a goal |
| PUT | `/api/v1/goals/{goal_id}` | Update goal progress |
| GET | `/api/v1/money-score` | Get current Money Score + component breakdown + 7-day history |
| GET | `/api/v1/money-dna` | Get Money DNA archetype classification |
| POST | `/api/v1/future-self/ask` | "Can I afford this?" — deterministic calc + LLM narrative |
| GET | `/api/v1/daily-brief` | Morning summary (wallet/bank fields are placeholder pending a balance-tracking feature — see `daily_brief.py`'s TODOs) |
| GET | `/api/v1/users/me/export` | Real data export (JSON) |
| DELETE | `/api/v1/users/me/ai-memory` | Hard-deletes AI conversation history |
| POST | `/api/v1/users/me/sessions/revoke-others` | Log out all other devices |

All response schemas use camelCase-aliased Pydantic models (`app/schemas/api.py`) so the wire format matches the mobile TS types exactly — this was verified by actually regenerating types and catching a real snake/camel mismatch bug, not assumed correct.

**Not yet built, flagged explicitly:** `/money-story` (Money Story feature currently reads seeded UI data, not a real endpoint), `/budgets` CRUD (budget data is currently seeded client-side in `useBudgetStore`, not fetched from the backend).

---

## 6. SMS Processing Pipeline

This is the core data-ingestion path for the whole product — worth its own detailed diagram given the strategic brief's emphasis on it.

```
┌──────────────────────────────────────────────────────────────────┐
│  ON-DEVICE (Android only — iOS cannot read SMS, platform policy)     │
│                                                                        │
│  1. Permission request                                                │
│     PermissionsAndroid.request(READ_SMS)                              │
│     (src/services/sms/smsListener.ts)                                 │
│                                                                        │
│  2a. Historical import (one-time, on permission grant)                 │
│      Read last 30 days of SMS inbox                                    │
│      → parseTransactionSmsBatch()                                      │
│                                                                        │
│  2b. Live listener (ongoing)                                           │
│      Subscribe to incoming SMS                                         │
│      → parseTransactionSms() per message                               │
│                                                                        │
│  3. Parse (src/services/sms/smsParser.ts) — regex-based, real:         │
│     a. isBankTransactionSms() — cheap pre-filter                       │
│        (has amount AND direction keyword AND account/balance ref)      │
│     b. Extract: amount, direction (credit/debit), account last-4,      │
│        balance, merchant (conservative — no match beats wrong match)   │
│     c. Assign confidence: high / medium / low based on how much        │
│        of the message was successfully parsed                          │
│                                                                        │
│  4. Client-side categorization (merchantCategorize.ts) — immediate     │
│     UI feedback before the round-trip to the backend                   │
│                                                                        │
│  5. User review (QuickAddSheet's SMS tab) — parsed transactions        │
│     shown for confirmation, especially low/medium-confidence ones,     │
│     not silently auto-saved                                            │
└───────────────────────────┬────────────────────────────────────────┘
                              │ POST /transactions
                              │ { merchant, amount, category,
                              │   source: "sms_parsed" }
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  BACKEND                                                              │
│                                                                        │
│  1. Re-categorize authoritatively via FIE's Categorizer                │
│     (server-side categorization is the source of truth;                │
│     client-side categorization is UI-speed-only, per                   │
│     merchantCategorize.ts's own docstring)                             │
│                                                                        │
│  2. Persist to `transactions` table, source="sms_parsed"                │
│                                                                        │
│  3. Triggers downstream (on next Money Score / Money DNA fetch):       │
│     Budget Engine recalculates spend-vs-allocated                      │
│     Money Score Engine recomputes from updated transaction set          │
└──────────────────────────────────────────────────────────────────┘
```

**Honest gap:** the native SMS-reading library (`react-native-get-sms-android` for one-shot reads, `react-native-android-sms-listener` for the live subscription) is **not yet installed** — the integration code in `smsListener.ts` is written correctly against their real documented APIs but commented out, because installing a native module with no way to build a custom Expo dev client in this environment would be dead weight. This is the single highest-priority "close this gap" item before Phase 1 can be considered done — see Implementation Plan Document v2.0 §3.

---

## 7. AI Pipeline

```
User message
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 1 — Scope pre-filter (gateway.py::is_offtopic)      │
│  Cheap regex check — code requests, image requests,         │
│  trivia rejected BEFORE any provider call                   │
└──────────────────────────┬────────────────────────────────┘
                             │ in scope
                             ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2 — Rate limit (gateway.py::check_and_increment_    │
│  usage) — Redis-backed, plan-aware (free: 30/day,            │
│  pro: 100/day). Capped users fall back to the static          │
│  Hinglish template bank, never hard-blocked.                  │
└──────────────────────────┬────────────────────────────────┘
                             │ within limit
                             ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3 — LangGraph Orchestrator (orchestrator.py)          │
│                                                               │
│    ┌──────┐   no tool call   ┌──────────┐                  │
│    │ think ├──────────────────▶ respond  ├──▶ final answer │
│    └───┬──┘                  └──────────┘                  │
│        │ tool call                                           │
│        ▼                                                     │
│  ┌─────────────┐                                            │
│  │ execute_tool │──▶ back to think (max 3 iterations)          │
│  └──────┬──────┘                                             │
│         │                                                     │
│         ▼                                                     │
│  TOOL_REGISTRY (tools.py): addExpense, updateGoal,             │
│  calculateSavings, forecastCashflow, checkBudgetStatus         │
│  — each calls into the FIE or DB directly, returns             │
│  structured data (never LLM-generated numbers)                 │
└──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│  System prompt enforcement (every LLM call)                  │
│  — Hinglish-only, personality-specific tone (6 personas),     │
│  hard content-safety rules for Roast Mode (never insults,     │
│  never attacks appearance/income/debt)                        │
└──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                  LiteLLM → OpenAI / Gemini / OpenRouter
                  (whichever is configured — provider-agnostic)
```

**Hallucination-prevention principle, enforced structurally throughout:** every number that reaches the user (Money Score, budget remaining, savings projection) is computed by deterministic Python in the FIE, never by the LLM. The LLM's role is narration and tool-selection, never arithmetic. This is why the FIE has zero LLM dependency and 26 passing unit tests that never touch a network call.

---

## 8. Deployment Architecture

### Current state (verified)
- Local dev: Docker Compose (Postgres + Redis + API), `docker-compose.yml`, confirmed to define all three services correctly.
- CI: GitHub Actions workflows now exist for both repos (`.github/workflows/ci.yml`) — backend runs pytest against real Postgres/Redis service containers, mobile runs `tsc`/ESLint/a full Metro export. Both validated as syntactically correct YAML; **not yet run against a live GitHub repo** since these projects aren't pushed yet.

### Target production topology (designed, not yet deployed)

```
┌─────────────┐     ┌──────────────────────────────────┐
│  Cloudflare   │────▶│  Backend (Railway or Render)        │
│  (DNS, WAF,   │     │  FastAPI + Uvicorn, Docker image     │
│  basic rate    │     │  from this repo's Dockerfile          │
│  limiting)     │     └──────────────┬───────────────────┘
└─────────────┘                        │
                          ┌────────────┼────────────┐
                          ▼            ▼             ▼
                   ┌───────────┐ ┌─────────┐ ┌──────────────┐
                   │ Postgres    │ │ Redis     │ │ Celery worker  │
                   │ (Supabase/  │ │ (Upstash) │ │ + beat          │
                   │  Neon)      │ │           │ │ (same image,    │
                   │             │ │           │ │ separate process│
                   │             │ │           │ │ — not deployed  │
                   │             │ │           │ │ yet)            │
                   └───────────┘ └─────────┘ └──────────────┘

┌─────────────────────────────────────────────────────────┐
│  Mobile — Expo EAS Build                                    │
│  eas build --profile development  → custom dev client         │
│  (needed for native SMS module — see §6's honest gap)          │
│  eas build --profile production   → real APK/AAB for Play      │
│  Store, once dev-client testing confirms SMS reading works      │
└─────────────────────────────────────────────────────────┘

Error tracking: Sentry (installed, DSN not yet configured)
Push notifications: Expo Push Notification service (free tier)
```

### CI/CD flow (built this pass)

```
git push → GitHub Actions triggers on paisaera-backend/** or apps/mobile/** changes
    │
    ├─ Backend: spin up Postgres+Redis service containers →
    │  install deps → py_compile syntax check → pytest (49 tests) →
    │  verify OpenAPI schema still generates cleanly
    │
    └─ Mobile: npm install → tsc --noEmit → eslint --max-warnings=0 →
       expo export --platform android (full Metro bundle,
       the same real verification used manually throughout this project)
```

**What's not yet built:** actual deployment automation (a `deploy` job that ships a passing `main` build to Railway/Render, or triggers an EAS build) — the CI workflows verify correctness but don't yet deploy anywhere. That's the natural next step once these repos are pushed to GitHub and hosting accounts exist (see `API_REQUIREMENTS.md`).
