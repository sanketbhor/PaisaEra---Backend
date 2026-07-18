"""
Tests for the Financial Intelligence Engine — pure functions, no DB or
network needed, which is exactly why this module was designed this way
(see the docstring in app/services/fie/engine.py). These run in
milliseconds and catch real regressions in the money math.
"""
import pytest

from app.services.fie.categorizer import categorize, is_recurring_candidate
from app.services.fie.budget_engine import (
    CategoryBudget,
    safe_to_spend_today,
    overspend_alerts,
    budget_discipline_ratio,
    days_left_in_month,
)
from app.services.fie.money_score_engine import (
    compute_money_score,
    score_budget_discipline,
    score_savings_behaviour,
    score_goal_achievement,
    BASE_SCORE,
    MAX_SCORE,
)
from app.services.fie.money_dna_engine import classify_money_dna
from app.services.fie.recommendation_engine import generate_recommendations
from app.services.fie.engine import fie


class TestCategorizer:
    def test_food_merchants(self):
        assert categorize("Swiggy order") == "Khana"
        assert categorize("ZOMATO*ORDER123") == "Khana"

    def test_shopping_merchants(self):
        assert categorize("Amazon Pay") == "Shopping"

    def test_investment_merchants(self):
        assert categorize("Zerodha SIP") == "Investment"

    def test_unknown_merchant_falls_back(self):
        assert categorize("Some Random XYZ Corp") == "Aur Kuch"

    def test_empty_merchant(self):
        assert categorize("") == "Aur Kuch"

    def test_recurring_candidate(self):
        assert is_recurring_candidate("Netflix Subscription") is True
        assert is_recurring_candidate("Random one-off purchase") is False


class TestBudgetEngine:
    def test_safe_to_spend_with_remaining_budget(self):
        categories = [CategoryBudget("Khana", allocated=6000, spent=3000)]
        result = safe_to_spend_today(categories)
        assert result >= 0

    def test_safe_to_spend_zero_when_over_budget(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=2000)]
        result = safe_to_spend_today(categories)
        assert result == 0

    def test_overspend_alerts_triggers_above_threshold(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=900)]
        alerts = overspend_alerts(categories, threshold=0.85)
        assert len(alerts) == 1
        assert alerts[0]["category"] == "Khana"

    def test_overspend_alerts_silent_below_threshold(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=500)]
        alerts = overspend_alerts(categories, threshold=0.85)
        assert len(alerts) == 0

    def test_budget_discipline_ratio_perfect(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=0)]
        assert budget_discipline_ratio(categories) == 1.0

    def test_budget_discipline_ratio_over_budget_floors_at_zero(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=5000)]
        assert budget_discipline_ratio(categories) == 0.0

    def test_days_left_in_month_is_positive(self):
        assert days_left_in_month() >= 1


class TestMoneyScoreEngine:
    def test_score_stays_within_bounds(self):
        result = compute_money_score(
            categories=[CategoryBudget("Khana", allocated=6000, spent=5200)],
            total_income_30d=65000,
            total_expense_30d=42000,
            goal_progress_ratios=[0.62, 0.24],
        )
        assert BASE_SCORE <= result.total_score <= MAX_SCORE

    def test_perfect_scores_hit_max_or_near_max(self):
        result = compute_money_score(
            categories=[CategoryBudget("Khana", allocated=1000, spent=0)],
            total_income_30d=100000,
            total_expense_30d=0,  # 100% savings rate
            goal_progress_ratios=[1.0, 1.0],
        )
        # BASE(500) + budget_discipline(150) + savings(150, capped) + goal(100) = 900, clamped to MAX_SCORE
        assert result.total_score == MAX_SCORE

    def test_zero_income_does_not_crash(self):
        result = compute_money_score(
            categories=[], total_income_30d=0, total_expense_30d=0, goal_progress_ratios=[]
        )
        assert result.total_score == BASE_SCORE  # no signal -> base score, not an error

    def test_no_goals_gives_zero_goal_points_not_a_crash(self):
        r = score_goal_achievement([])
        assert r.points == 0

    def test_savings_behaviour_negative_savings_floors_at_zero(self):
        r = score_savings_behaviour(total_income_30d=1000, total_expense_30d=2000)
        assert r.points == 0

    def test_level_labels_match_score_ranges(self):
        assert compute_money_score([], 0, 0, []).level == "Money Starter"
        high_score = compute_money_score(
            categories=[CategoryBudget("X", allocated=1000, spent=0)],
            total_income_30d=100000,
            total_expense_30d=0,
            goal_progress_ratios=[1.0],
        )
        assert high_score.level in ("Money Master", "Money Builder")


class TestMoneyDNAEngine:
    def test_classify_returns_three_item_breakdown(self):
        result = classify_money_dna({"Investment": 0.3, "Khana": 0.3, "Shopping": 0.2}, savings_rate=0.2)
        assert len(result.breakdown) == 3

    def test_breakdown_percentages_sum_to_100(self):
        result = classify_money_dna({"Investment": 0.4, "Khana": 0.2}, savings_rate=0.3)
        total_pct = sum(b["pct"] for b in result.breakdown)
        assert total_pct == 100

    def test_high_investment_and_savings_gives_strategic_builder(self):
        result = classify_money_dna({"Investment": 0.5}, savings_rate=0.3)
        assert result.primary_archetype == "Strategic Builder"


class TestRecommendationEngine:
    def test_generates_recommendation_for_overspend(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=900)]
        recs = generate_recommendations(categories, income=50000)
        assert len(recs) == 1
        assert recs[0].confidence == "high"
        assert "Khana" in recs[0].summary

    def test_no_recommendations_when_within_budget(self):
        categories = [CategoryBudget("Khana", allocated=1000, spent=200)]
        recs = generate_recommendations(categories, income=50000)
        assert len(recs) == 0


class TestFIEOrchestrator:
    def test_categorize_transaction_returns_expected_shape(self):
        result = fie.categorize_transaction("Swiggy order")
        assert result["category"] == "Khana"
        assert "is_recurring_candidate" in result

    def test_compute_snapshot_returns_all_pieces(self):
        snapshot = fie.compute_snapshot(
            categories=[CategoryBudget("Khana", allocated=6000, spent=3000)],
            total_income_30d=50000,
            total_expense_30d=30000,
            goal_progress_ratios=[0.5],
            category_spend_pct={"Khana": 1.0},
            monthly_income=50000,
        )
        assert snapshot.money_score.total_score > 0
        assert snapshot.money_dna.primary_archetype
        assert isinstance(snapshot.recommendations, list)
        assert snapshot.safe_to_spend_today >= 0
