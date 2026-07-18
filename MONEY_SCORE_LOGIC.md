# Money Score — How It's Actually Calculated

This is the plain-English explanation of what `app/services/fie/money_score_engine.py` computes — referenced from the mobile app's "ℹ️ How is this calculated?" bottom sheet, which shows the *real* output of this logic, not a mockup.

## The formula

```
Money Score = BASE_SCORE (500) + sum of component points, clamped to [0, 850]
```

**Why 500 as a base, not 0:** a brand-new user with zero data shouldn't see "0/850" — that reads as a failing grade for someone who's done nothing wrong, they just haven't used the app yet. 500 is a neutral starting point; every component only ever *adds* points, never subtracts below that floor.

## The 8 components (per the PRD's Financial Intelligence Engine spec)

| Component | Weight (max points) | Status |
|---|---|---|
| Budget Discipline | 150 | **Implemented** |
| Savings Behaviour | 150 | **Implemented** |
| Goal Achievement | 100 | **Implemented** |
| Expense Behaviour | 100 | Not implemented — contributes 0 |
| Money Habits | 100 | Not implemented — contributes 0 |
| Income Stability | 100 | Not implemented — contributes 0 |
| Financial Awareness | 100 | Not implemented — contributes 0 |
| Financial Safety | 100 | Not implemented — contributes 0 |

**Why only 3 of 8 are implemented:** each of the other 5 needs a real data source that doesn't exist yet in this phase (Income Stability needs multiple months of salary-credit history to detect regularity; Financial Safety needs an actual emergency-fund tracking feature; Financial Awareness would need to measure engagement with the Insights/education content). Implementing them now would mean either faking the number or leaving it at a placeholder — the codebase does neither; it explicitly contributes 0 and is documented as not-yet-built, both here and in the API response itself (the mobile app's info sheet only shows components that are actually computed).

### 1. Budget Discipline (150 pts)

```
ratio = 1 - (total_spent / total_allocated)   # capped at 0 if over budget
points = 150 * ratio
```

If you've spent exactly your budget, ratio = 0, you get 0 points from this component. If you've spent half your budget with the month still going, ratio = 0.5, you get 75 points. Going over budget entirely zeroes this component out — it does not go negative.

### 2. Savings Behaviour (150 pts)

```
savings_rate = max(0, (income_30d - expense_30d) / income_30d)
points = 150 * min(1, savings_rate * 2)
```

The `* 2` means a 50% savings rate maxes out this component — deliberately generous, since a 50% savings rate is already excellent and shouldn't require an unrealistic 100% to reach full points.

### 3. Goal Achievement (100 pts)

```
avg_progress = average(current_amount / target_amount) across all active goals
points = 100 * min(1, avg_progress)
```

Simple average of how far along your goals are. A single goal at 60% progress gives 60 points; two goals at 40% and 80% average to 60% and also give 60 points.

## The level label ("Money Builder", etc.)

```
score >= 800 -> "Money Master"
score >= 700 -> "Money Builder"
score >= 600 -> "Money Learner"
else         -> "Money Starter"
```

Purely a display label derived from the final score — no separate calculation.

## What's genuinely NOT happening

- **No LLM involvement in the number itself.** The score is deterministic Python arithmetic over real transaction/budget/goal data pulled from Postgres. The AI Gateway is never asked to "estimate" or "guess" a score — this is a hard architectural rule carried through the whole FIE (see the TRD's hallucination-prevention principle), because a financial score that sometimes hallucinates would destroy trust the moment a user noticed.
- **No historical weighting or decay yet** — the score is recomputed from current-state data each time `/money-score` is called (or by the nightly Celery job once that's running in production — see `app/workers/celery_app.py`), not smoothed over time. A single very good or very bad day can swing it more than a mature version of this system probably should. Worth revisiting once there's enough real usage data to tune reasonable smoothing.
- **Weights (150/150/100/100/100/100/100/100) are a starting point, not researched values.** They were chosen to feel roughly reasonable, not derived from any user study. Expect to tune these once you have real cohort data on what actually correlates with good financial outcomes.
