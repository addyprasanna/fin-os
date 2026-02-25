"""
Build a simulation config from user-supplied inputs.
Used by the web app and any other entry points that collect user data.
"""
from datetime import date


def _parse_date(value):
    """Parse date from string (YYYY-MM-DD) or return as-is if already a date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    return None


def build_scenario(
    *,
    accounts=None,
    debts=None,
    income=None,
    expenses=None,
    start_date=None,
    months=120,
    cash_account=None,
    goal_net_worth=None,
    payment_guess=0.0,
    monthly_investing=0.0,
    monthly_investing_pct=0.0,
):
    """
    Build an engine-compatible config from user inputs.

    Args:
        accounts: List of dicts with name, balance, rate_schedule (number or
            dict with promo_end, promo_apr, standard_apr), type ("cash" or "invest").
        debts: List of dicts with name, balance, apr_schedule (number or dict
            with promo_end, promo_apr, standard_apr), min_payment_rule
            (dict with type "fixed"|"percent" and amount or rate).
        income: List of dicts with name, amount, cadence ("monthly"|"biweekly").
        expenses: List of dicts with name, amount, cadence ("monthly"|"biweekly").
        start_date: Simulation start (date or "YYYY-MM-DD").
        months: Max months for fixed runs.
        cash_account: Name of account used for cash (default first account).
        goal_net_worth: Target net worth for "until goal" mode (optional).
        payment_guess: Extra monthly payment toward debt.
        monthly_investing: Fixed monthly amount to transfer to investing account (optional).
        monthly_investing_pct: Alternatively, percentage of monthly income to invest (0–100). If set, overrides fixed amount.

    Returns:
        Config dict suitable for engine.simulate().
    """
    accounts = list(accounts or [])
    debts = list(debts or [])
    income = list(income or [])
    expenses = list(expenses or [])

    # Normalize accounts
    out_accounts = []
    for a in accounts:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        balance = float(a.get("balance", 0))
        rate = a.get("rate_schedule", 0)
        if isinstance(rate, dict):
            rs = {}
            if "promo_end" in rate:
                rs["promo_end"] = _parse_date(rate["promo_end"]) or date.today()
            rs["promo_apr"] = float(rate.get("promo_apr", 0))
            rs["standard_apr"] = float(rate.get("standard_apr", 0))
            rate_schedule = rs
        else:
            rate_schedule = float(rate) if rate not in (None, "") else 0.0
        acc_type = (a.get("type") or "cash").strip().lower() or "cash"
        if acc_type not in ("cash", "invest"):
            acc_type = "cash"
        out_accounts.append({
            "name": name,
            "balance": balance,
            "rate_schedule": rate_schedule,
            "type": acc_type,
        })

    # Normalize debts
    out_debts = []
    for d in debts:
        name = (d.get("name") or "").strip()
        if not name:
            continue
        balance = float(d.get("balance", 0))
        apr = d.get("apr_schedule", 0)
        if isinstance(apr, dict):
            apr_schedule = {
                "promo_end": _parse_date(apr.get("promo_end")),
                "promo_apr": float(apr.get("promo_apr", 0)),
                "standard_apr": float(apr.get("standard_apr", 0)),
            }
            if apr_schedule["promo_end"] is None:
                apr_schedule.pop("promo_end", None)
        else:
            apr_schedule = float(apr) if apr not in (None, "") else 0.0
        min_rule = d.get("min_payment_rule") or {}
        rule_type = (min_rule.get("type") or "fixed").strip() or "fixed"
        if rule_type == "percent":
            min_payment_rule = {"type": "percent", "rate": float(min_rule.get("rate", 0))}
        else:
            min_payment_rule = {"type": "fixed", "amount": float(min_rule.get("amount", 0))}
        out_debts.append({
            "name": name,
            "balance": balance,
            "apr_schedule": apr_schedule,
            "min_payment_rule": min_payment_rule,
            "start_date": _parse_date(d.get("start_date")),
        })

    # Normalize income
    out_income = []
    for i in income:
        name = (i.get("name") or "").strip()
        if not name:
            continue
        out_income.append({
            "name": name,
            "amount": float(i.get("amount", 0)),
            "cadence": (i.get("cadence") or "monthly").strip() or "monthly",
            "start_date": _parse_date(i.get("start_date")),
            "end_date": _parse_date(i.get("end_date")),
        })

    # Normalize expenses
    out_expenses = []
    for e in expenses:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        out_expenses.append({
            "name": name,
            "amount": float(e.get("amount", 0)),
            "cadence": (e.get("cadence") or "monthly").strip() or "monthly",
        })

    start = _parse_date(start_date) or date.today()
    cash = (cash_account or "").strip()
    if not cash and out_accounts:
        cash = out_accounts[0]["name"]

    # Optional investing: fixed amount and/or % of income
    investing_val = float(monthly_investing or 0)
    investing_pct = float(monthly_investing_pct or 0)
    needs_investing_account = investing_val > 0 or investing_pct > 0
    investing_account_name = None
    if needs_investing_account:
        # Use first existing investment account, or create "Investments"
        invest_accounts = [a for a in out_accounts if a.get("type") == "invest"]
        if invest_accounts:
            investing_account_name = invest_accounts[0]["name"]
        else:
            investing_account_name = "Investments"
            out_accounts.append({
                "name": investing_account_name,
                "balance": 0.0,
                "rate_schedule": 0.0,
                "type": "invest",
            })

    goal = None
    if goal_net_worth is not None and goal_net_worth != "":
        try:
            goal = float(goal_net_worth)
        except (TypeError, ValueError):
            goal = None

    payment_guess_val = float(payment_guess or 0)

    return {
        "instruments": {
            "accounts": out_accounts,
            "debts": out_debts,
        },
        "cashflow_streams": {
            "income": out_income,
            "expenses": out_expenses,
        },
        "simulation": {
            "start_date": start,
            "months": int(months) if months is not None else 120,
            "cash_account": cash or (out_accounts[0]["name"] if out_accounts else "HYSA"),
            "goal_net_worth": goal,
            "monthly_investing": investing_val,
            "monthly_investing_pct": investing_pct,
            "investing_account": investing_account_name if needs_investing_account else None,
        },
        "payment_guess": payment_guess_val,
    }
