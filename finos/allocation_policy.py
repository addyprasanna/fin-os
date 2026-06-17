"""
Rule-based allocation policy: decides how much cash to transfer to each
investment account and how much to pay to each debt each month.

Returns {debt_payments: {debt_name: amount}, contributions: {account_name: amount}}.
Pure and testable: no I/O, only dicts in/out.
"""
from datetime import date


def _get_rate_for_date(rate_schedule, current_date):
    """Get applicable annual rate from a schedule (number or dict with promo)."""
    if isinstance(rate_schedule, (int, float)):
        return float(rate_schedule)
    if isinstance(rate_schedule, dict):
        if rate_schedule.get("promo_end") and current_date < rate_schedule["promo_end"]:
            return float(rate_schedule.get("promo_apr", 0))
        return float(rate_schedule.get("standard_apr", 0))
    return 0.0


def _min_payment(debt, current_balance):
    """Minimum payment for a debt."""
    rule = debt.get("min_payment_rule") or {}
    t = (rule.get("type") or "fixed").strip()
    if t == "percent":
        return current_balance * float(rule.get("rate", 0))
    return float(rule.get("amount", 0))


def allocation_policy(
    *,
    current_date,
    accounts_config,
    debts_config,
    account_balances,
    debt_balances,
    cash_landing_account,
    emergency_floor=0.0,
):
    """
    Rule-based allocation for one month.

    Rules:
    1. Pay minimums on all debts (from cash landing).
    2. Keep cash >= emergency_floor (surplus = cash - floor after mins).
    3. Contribute up to monthly_target for each investment account (order: list order).
    4. Send remaining surplus to highest APR debt; if all debts paid, to first investment (brokerage).

    Args:
        current_date: Date for the month (for APR schedules).
        accounts_config: List of account dicts with name, kind, annual_return, optional monthly_target.
        debts_config: List of debt dicts with name, apr_schedule, min_payment_rule.
        account_balances: Dict name -> balance (will not be mutated).
        debt_balances: Dict name -> balance (will not be mutated).
        cash_landing_account: Name of the cash account (income/expenses land here).
        emergency_floor: Minimum cash to keep in cash_landing_account after allocations.

    Returns:
        {"debt_payments": {debt_name: amount}, "contributions": {account_name: amount}}
    """
    cash = max(0.0, float(account_balances.get(cash_landing_account, 0)))
    debt_payments = {}
    contributions = {}

    # 1. Pay minimums on all debts
    for debt in debts_config:
        name = debt["name"]
        balance = debt_balances.get(name, 0)
        if balance <= 0:
            debt_payments[name] = 0.0
            continue
        min_pay = _min_payment(debt, balance)
        pay = min(min_pay, balance, cash)
        debt_payments[name] = pay
        cash -= pay

    # Surplus available for investments and extra debt (must keep cash >= emergency_floor)
    surplus = max(0.0, cash - emergency_floor)

    # 2. Investment accounts with monthly_target (in config order)
    investment_accounts = [
        a for a in accounts_config
        if (a.get("kind") or a.get("type") or "cash").lower() in ("invest", "investment")
    ]
    for acc in investment_accounts:
        if surplus <= 0:
            break
        target = float(acc.get("monthly_target") or 0)
        if target <= 0:
            continue
        contrib = min(target, surplus)
        if contrib > 0:
            contributions[acc["name"]] = contrib
            surplus -= contrib

    # 3. Remaining surplus: highest APR debt first (avalanche), then first investment if no debts
    debts_with_balance = [
        (d["name"], debt_balances.get(d["name"], 0), _get_rate_for_date(d.get("apr_schedule", 0), current_date))
        for d in debts_config
        if debt_balances.get(d["name"], 0) > 0
    ]
    debts_with_balance.sort(key=lambda x: -x[2])  # highest APR first

    if surplus > 0 and debts_with_balance:
        # Apply to highest APR debt
        name, balance, _ = debts_with_balance[0]
        extra = min(surplus, balance)
        if extra > 0:
            debt_payments[name] = debt_payments.get(name, 0) + extra
            surplus -= extra
    elif surplus > 0 and investment_accounts:
        # All debts paid; send remainder to first investment account
        first_inv = investment_accounts[0]["name"]
        contributions[first_inv] = contributions.get(first_inv, 0) + surplus
        surplus = 0

    return {"debt_payments": debt_payments, "contributions": contributions}
