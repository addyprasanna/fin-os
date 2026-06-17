"""
Financial simulation engine.

Loop each month: apply income → apply expenses (to cash_landing_account only) →
apply returns on all accounts → apply debt interest → allocation policy (transfers/payments) → log.

Accounts have kind: "cash" | "investment" and annual_return (APY or expected return).
"""
from datetime import date

from allocation_policy import allocation_policy


def _add_months(d, n):
    """Add n months to date d (same day, clamp to last day of month)."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    if month == 2:
        ndays = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    else:
        ndays = [31, 0, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(d.day, ndays)
    return date(year, month, day)


def _get_rate_for_date(rate_schedule, current_date):
    """Get the applicable rate for a given date from a rate schedule."""
    if isinstance(rate_schedule, (int, float)):
        return float(rate_schedule)
    if isinstance(rate_schedule, dict):
        if rate_schedule.get("promo_end") and current_date < rate_schedule["promo_end"]:
            return float(rate_schedule.get("promo_apr", 0))
        return float(rate_schedule.get("standard_apr", 0))
    return 0.0


def _is_stream_active(stream, current_date):
    if stream.get("start_date") and current_date < stream["start_date"]:
        return False
    if stream.get("end_date") and current_date >= stream["end_date"]:
        return False
    return True


def _get_stream_amount(stream, current_date):
    if not _is_stream_active(stream, current_date):
        return 0.0
    cadence = stream.get("cadence", "monthly")
    amount = float(stream.get("amount", 0))
    if cadence == "biweekly":
        return amount * (26 / 12)
    return amount


# ---------------------------------------------------------------------------
# Normalize config to canonical account shape: kind, annual_return, monthly_target
# ---------------------------------------------------------------------------

def _normalize_account(acc):
    """Return dict with name, balance, kind ('cash'|'investment'), annual_return, monthly_target."""
    name = (acc.get("name") or "").strip()
    balance = float(acc.get("balance", 0))
    kind = (acc.get("kind") or acc.get("type") or "cash").strip().lower()
    if kind not in ("cash", "investment", "invest"):
        kind = "cash"
    if kind == "invest":
        kind = "investment"
    # annual_return: prefer annual_return, else rate_schedule (number or from schedule)
    ar = acc.get("annual_return")
    if ar is not None:
        annual_return = float(ar)
    else:
        rs = acc.get("rate_schedule", 0)
        annual_return = _get_rate_for_date(rs, date.today()) if isinstance(rs, dict) else float(rs or 0)
    monthly_target = float(acc.get("monthly_target") or 0)
    return {
        "name": name,
        "balance": balance,
        "kind": kind,
        "annual_return": annual_return,
        "monthly_target": monthly_target,
    }


def _normalize_accounts_for_policy(accounts_normalized):
    """List of account dicts for policy: name, kind, monthly_target (policy accepts kind or type)."""
    return [
        {"name": a["name"], "kind": a["kind"], "monthly_target": a["monthly_target"]}
        for a in accounts_normalized
    ]


# ---------------------------------------------------------------------------
# Public helpers (used by run.py, tests, UI)
# ---------------------------------------------------------------------------

def get_monthly_cashflows(config, current_date):
    """(income_total, expense_total) for the given date."""
    streams = config.get("cashflow_streams", {})
    income_total = sum(_get_stream_amount(s, current_date) for s in streams.get("income", []))
    expense_total = sum(_get_stream_amount(s, current_date) for s in streams.get("expenses", []))
    return (income_total, expense_total)


def get_account(config, name):
    """Get account config by name (original shape). Returns None if not found."""
    for acc in config.get("instruments", {}).get("accounts", []):
        if acc.get("name") == name:
            return acc
    return None


def debt_monthly_rate(debt, current_date):
    apr = _get_rate_for_date(debt.get("apr_schedule", 0), current_date)
    return apr / 12.0


def min_payment(debt, current_balance):
    rule = debt.get("min_payment_rule") or {}
    t = (rule.get("type") or "fixed").strip()
    if t == "percent":
        return current_balance * float(rule.get("rate", 0))
    return float(rule.get("amount", 0))


# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------

def simulate(config, start_date=None, months=None, cash_landing_account=None, stop_mode="debt"):
    """
    Month-by-month simulation.

    Order each month:
    1. Apply income to cash_landing_account
    2. Apply expenses from cash_landing_account
    3. Apply returns on all accounts (annual_return/12)
    4. Apply debt interest
    5. Allocation policy → debt_payments, contributions
    6. Apply payments and contributions (from cash to debts / to investment accounts)
    7. Log

    Args:
        config: instruments.accounts (with kind, annual_return or rate_schedule), instruments.debts,
                cashflow_streams, simulation (start_date, months, cash_landing_account or cash_account, emergency_floor, goal_net_worth).
        start_date, months, cash_landing_account: Override config.
        stop_mode: "fixed" | "debt" | "goal"

    Returns:
        List of monthly records (date, accounts, debts, income, expenses, payments, contributions, account_interest, debt_interest, totals, net_worth, monthly_surplus).
    """
    sim_cfg = config.get("simulation", {})
    start_date = start_date or sim_cfg.get("start_date")
    if start_date is None:
        start_date = date.today()
    months = months or sim_cfg.get("months", 120)
    # Prefer cash_landing_account, then legacy cash_account
    cash_landing = cash_landing_account or sim_cfg.get("cash_landing_account") or sim_cfg.get("cash_account", "HYSA")
    emergency_floor = float(sim_cfg.get("emergency_floor") or 0)
    goal_net_worth = sim_cfg.get("goal_net_worth")

    instruments = config.get("instruments", {})
    accounts_raw = instruments.get("accounts", [])
    debts_config = instruments.get("debts", [])

    # Normalize accounts: ensure we have at least one cash account
    accounts_normalized = [_normalize_account(a) for a in accounts_raw if (a.get("name") or "").strip()]
    if not accounts_normalized:
        raise ValueError("No accounts in config")
    # If no cash account, treat first as cash
    has_cash = any(a["kind"] == "cash" for a in accounts_normalized)
    if not has_cash:
        accounts_normalized[0]["kind"] = "cash"
    # Resolve cash_landing: must be a cash account name
    names = [a["name"] for a in accounts_normalized]
    if cash_landing not in names:
        cash_landing = next((a["name"] for a in accounts_normalized if a["kind"] == "cash"), names[0])

    account_balances = {a["name"]: a["balance"] for a in accounts_normalized}
    debt_balances = {d["name"]: float(d.get("balance", 0)) for d in debts_config}

    records = []
    current = start_date

    for _ in range(months):
        if stop_mode == "debt" and all(b <= 0 for b in debt_balances.values()):
            break

        month_start_accounts = dict(account_balances)
        month_start_debts = dict(debt_balances)

        # 1. Income and expenses only on cash_landing_account
        income_total, expense_total = get_monthly_cashflows(config, current)
        account_balances[cash_landing] = account_balances.get(cash_landing, 0) + income_total - expense_total

        # 2. Apply returns on all accounts (before policy)
        account_interest = {}
        for a in accounts_normalized:
            name = a["name"]
            bal = account_balances.get(name, 0)
            if bal > 0:
                monthly_rate = a["annual_return"] / 12.0
                interest = bal * monthly_rate
                account_balances[name] = bal + interest
                account_interest[name] = interest

        # 3. Debt interest
        debt_interest = {}
        for debt in debts_config:
            name = debt["name"]
            bal = debt_balances.get(name, 0)
            if bal > 0:
                mr = debt_monthly_rate(debt, current)
                debt_interest[name] = bal * mr
                debt_balances[name] = bal + debt_interest[name]

        # 4. Allocation policy
        policy_result = allocation_policy(
            current_date=current,
            accounts_config=_normalize_accounts_for_policy(accounts_normalized),
            debts_config=debts_config,
            account_balances=dict(account_balances),
            debt_balances=dict(debt_balances),
            cash_landing_account=cash_landing,
            emergency_floor=emergency_floor,
        )
        debt_payments = policy_result["debt_payments"]
        contributions = policy_result["contributions"]

        # 5. Apply debt payments (from cash_landing)
        for name, amount in debt_payments.items():
            if amount <= 0:
                continue
            cash_available = max(0, account_balances.get(cash_landing, 0))
            pay = min(amount, debt_balances.get(name, 0), cash_available)
            if pay > 0:
                debt_balances[name] = debt_balances.get(name, 0) - pay
                account_balances[cash_landing] = account_balances.get(cash_landing, 0) - pay

        # 6. Apply contributions (from cash_landing to investment accounts)
        for name, amount in contributions.items():
            if amount <= 0 or name not in account_balances:
                continue
            cash_available = max(0, account_balances.get(cash_landing, 0))
            contrib = min(amount, cash_available)
            if contrib > 0:
                account_balances[cash_landing] = account_balances.get(cash_landing, 0) - contrib
                account_balances[name] = account_balances.get(name, 0) + contrib

        total_accounts = sum(account_balances.values())
        total_debts = sum(debt_balances.values())
        net_worth = total_accounts - total_debts
        total_payments = sum(debt_payments.values())
        total_contributions = sum(contributions.values())
        monthly_surplus = income_total - expense_total - total_payments - total_contributions

        rec = {
            "date": current,
            "accounts": {n: round(b, 2) for n, b in account_balances.items()},
            "debts": {n: round(b, 2) for n, b in debt_balances.items()},
            "accounts_start": {n: round(b, 2) for n, b in month_start_accounts.items()},
            "debts_start": {n: round(b, 2) for n, b in month_start_debts.items()},
            "income": round(income_total, 2),
            "expenses": round(expense_total, 2),
            "payments": {n: round(amt, 2) for n, amt in debt_payments.items()},
            "contributions": {n: round(amt, 2) for n, amt in contributions.items()},
            "account_interest": {n: round(amt, 2) for n, amt in account_interest.items()},
            "debt_interest": {n: round(amt, 2) for n, amt in debt_interest.items()},
            "total_accounts": round(total_accounts, 2),
            "total_debts": round(total_debts, 2),
            "net_worth": round(net_worth, 2),
            "monthly_surplus": round(monthly_surplus, 2),
        }
        records.append(rec)

        if stop_mode == "goal" and goal_net_worth is not None and net_worth >= goal_net_worth:
            break

        current = _add_months(current, 1)

    return records
