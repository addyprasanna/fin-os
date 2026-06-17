"""
Tests for the financial simulation engine and allocation policy.

(a) Investments only increase via contributions + returns.
(b) Expenses never come from investment accounts.
(c) Cash never drops below emergency floor unless income < expenses + minimums.
"""
from datetime import date
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "finos"))

from engine import simulate
from allocation_policy import allocation_policy


def _config(accounts, debts, income, expenses, emergency_floor=0, cash_landing="Cash"):
    return {
        "instruments": {"accounts": accounts, "debts": debts},
        "cashflow_streams": {"income": income, "expenses": expenses},
        "simulation": {
            "start_date": date(2025, 1, 1),
            "months": 24,
            "cash_landing_account": cash_landing,
            "emergency_floor": emergency_floor,
            "goal_net_worth": None,
        },
    }


def test_investments_only_increase_via_contributions_and_returns():
    """(a) Investment account balance only increases from contributions + returns, never from income/expense flows."""
    config = _config(
        accounts=[
            {"name": "Cash", "balance": 10_000, "kind": "cash", "annual_return": 0.04},
            {"name": "Brokerage", "balance": 1_000, "kind": "investment", "annual_return": 0.07, "monthly_target": 500},
        ],
        debts=[],
        income=[{"name": "Salary", "amount": 6_000, "cadence": "monthly"}],
        expenses=[{"name": "Rent", "amount": 2_000, "cadence": "monthly"}],
        emergency_floor=1_000,
        cash_landing="Cash",
    )
    records = simulate(config, stop_mode="fixed")
    assert len(records) >= 2
    start_brokerage = records[0]["accounts_start"].get("Brokerage", 0)
    for r in records:
        brokerage_now = r["accounts"].get("Brokerage", 0)
        brokerage_start = r["accounts_start"].get("Brokerage", 0)
        contrib = r.get("contributions", {}).get("Brokerage", 0)
        # Change in brokerage = contributions + return on start balance (and on new money already in month)
        # So brokerage_now >= brokerage_start + contrib (return can only add)
        assert brokerage_now >= brokerage_start + contrib - 0.01, (
            f"Brokerage should only grow by contributions + returns: {brokerage_start} -> {brokerage_now}, contrib={contrib}"
        )
    # Total increase in brokerage over simulation = sum(contributions) + returns
    total_contrib = sum(r.get("contributions", {}).get("Brokerage", 0) for r in records)
    first_brokerage = records[0]["accounts_start"].get("Brokerage", 0)
    last_brokerage = records[-1]["accounts"].get("Brokerage", 0)
    assert last_brokerage >= first_brokerage + total_contrib - 0.01


def test_expenses_never_come_from_investment_accounts():
    """(b) Income and expenses only affect cash_landing_account; investment balances never decrease from expenses."""
    config = _config(
        accounts=[
            {"name": "Cash", "balance": 5_000, "kind": "cash", "annual_return": 0.04},
            {"name": "Roth", "balance": 20_000, "kind": "investment", "annual_return": 0.06, "monthly_target": 200},
        ],
        debts=[{"name": "Card", "balance": 1_000, "apr_schedule": 0.18, "min_payment_rule": {"type": "fixed", "amount": 50}}],
        income=[{"name": "Job", "amount": 4_000, "cadence": "monthly"}],
        expenses=[{"name": "Bills", "amount": 3_000, "cadence": "monthly"}],
        emergency_floor=500,
        cash_landing="Cash",
    )
    records = simulate(config, stop_mode="fixed")
    assert len(records) >= 1
    for r in records:
        roth_before = r["accounts_start"].get("Roth", 0)
        roth_after = r["accounts"].get("Roth", 0)
        contrib = r.get("contributions", {}).get("Roth", 0)
        # Roth can only go up by contribution + return; expenses never touch it
        assert roth_after >= roth_before + contrib - 0.01, (
            f"Roth should not decrease from expenses: {roth_before} -> {roth_after}, contrib={contrib}"
        )


def test_cash_never_below_emergency_floor_unless_income_insufficient():
    """(c) After applying policy, cash_landing balance never goes below emergency_floor unless income - expenses - minimums < 0."""
    config = _config(
        accounts=[
            {"name": "Cash", "balance": 8_000, "kind": "cash", "annual_return": 0.04},
            {"name": "Brokerage", "balance": 0, "kind": "investment", "annual_return": 0.07, "monthly_target": 1_000},
        ],
        debts=[{"name": "Loan", "balance": 5_000, "apr_schedule": 0.12, "min_payment_rule": {"type": "fixed", "amount": 100}}],
        income=[{"name": "Salary", "amount": 5_000, "cadence": "monthly"}],
        expenses=[{"name": "Rent", "amount": 2_500, "cadence": "monthly"}],
        emergency_floor=2_000,
        cash_landing="Cash",
    )
    records = simulate(config, stop_mode="fixed")
    assert len(records) >= 1
    for r in records:
        cash_after = r["accounts"].get("Cash", 0)
        income = r["income"]
        expenses = r["expenses"]
        total_mins = sum(
            max(0, 100)  # min payment 100 for Loan
            for _ in [1]
        )
        # If income - expenses >= minimums, we should never go below emergency_floor (policy keeps surplus only above floor)
        if income - expenses >= 100:  # at least minimum can be paid
            assert cash_after >= 2_000 - 0.01, (
                f"Cash should not drop below emergency_floor when income suffices: cash={cash_after}, floor=2000"
            )
    # Also verify: in a month where income < expenses + minimums, we allow cash to go below floor
    config_tight = _config(
        accounts=[{"name": "Cash", "balance": 2_500, "kind": "cash", "annual_return": 0}],
        debts=[{"name": "D", "balance": 500, "apr_schedule": 0.1, "min_payment_rule": {"type": "fixed", "amount": 50}}],
        income=[{"name": "I", "amount": 2_000, "cadence": "monthly"}],
        expenses=[{"name": "E", "amount": 2_500, "cadence": "monthly"}],
        emergency_floor=1_000,
    )
    records_tight = simulate(config_tight, stop_mode="fixed")
    # Income 2000 - expenses 2500 = -500; we pay min 50 from cash; cash can drop below 1000
    assert len(records_tight) >= 1
    # After first month: cash started 2500, +2000-2500-50 = 1950. So we're above floor. Run more months to get below.
    # Actually -500 net + we pay 50 so -550 from cash. 2500 - 550 = 1950. So still above 1000.
    # To test "unless income < expenses + mins" we need a scenario where cash would go below floor. So: income 1000, expenses 1500, mins 100, floor 1000, start cash 800. Then 800+1000-1500-100 = 200 < 1000. So we allow that.
    config_below = _config(
        accounts=[{"name": "Cash", "balance": 800, "kind": "cash", "annual_return": 0}],
        debts=[{"name": "D", "balance": 200, "apr_schedule": 0.1, "min_payment_rule": {"type": "fixed", "amount": 100}}],
        income=[{"name": "I", "amount": 1_000, "cadence": "monthly"}],
        expenses=[{"name": "E", "amount": 1_500, "cadence": "monthly"}],
        emergency_floor=1_000,
    )
    recs_below = simulate(config_below, stop_mode="fixed")
    assert len(recs_below) >= 1
    cash_after_first = recs_below[0]["accounts"]["Cash"]
    # 800 + 1000 - 1500 - 100 = 200. So cash goes below floor when income can't cover expenses + mins.
    assert cash_after_first < 1_000
    assert cash_after_first >= 0
