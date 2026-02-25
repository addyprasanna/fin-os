from datetime import date


def _add_months(d, n):
    """Add n months to date d (same day, clamp to last day of month)."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    # Last day of target month
    if month == 2:
        ndays = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    else:
        ndays = [31, 0, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(d.day, ndays)
    return date(year, month, day)


def _is_stream_active(stream, current_date):
    """Check if a cashflow stream is active for the given date."""
    start = stream.get("start_date")
    end = stream.get("end_date")
    if start and current_date < start:
        return False
    if end and current_date >= end:
        return False
    return True


def _get_stream_amount(stream, current_date):
    """Get the amount for a cashflow stream, accounting for cadence."""
    if not _is_stream_active(stream, current_date):
        return 0.0
    
    cadence = stream.get("cadence", "monthly")
    amount = float(stream.get("amount", 0))
    
    if cadence == "monthly":
        return amount
    elif cadence == "biweekly":
        # Biweekly: 26 payments per year = 26/12 per month
        return amount * (26 / 12)
    return amount


def _get_rate_for_date(rate_schedule, current_date):
    """Get the applicable rate for a given date from a rate schedule."""
    if isinstance(rate_schedule, (int, float)):
        return float(rate_schedule)
    elif isinstance(rate_schedule, dict):
        if "promo_end" in rate_schedule:
            if current_date < rate_schedule["promo_end"]:
                return float(rate_schedule["promo_apr"])
            else:
                return float(rate_schedule["standard_apr"])
    return 0.0


# ============================================================================
# Step A: Pure helper functions
# ============================================================================

def get_monthly_cashflows(config, current_date):
    """
    Compute total income and expenses for a given date.
    
    Returns:
        tuple: (income_total, expense_total)
    """
    cashflow_streams = config.get("cashflow_streams", {})
    income_streams = cashflow_streams.get("income", [])
    expense_streams = cashflow_streams.get("expenses", [])
    
    income_total = sum(_get_stream_amount(stream, current_date) for stream in income_streams)
    expense_total = sum(_get_stream_amount(stream, current_date) for stream in expense_streams)
    
    return (income_total, expense_total)


def get_account(config, name):
    """
    Get an account by name from config.
    
    Returns:
        dict: Account configuration, or None if not found
    """
    instruments = config.get("instruments", {})
    accounts = instruments.get("accounts", [])
    
    for acc in accounts:
        if acc["name"] == name:
            return acc
    return None


def debt_monthly_rate(debt, current_date):
    """
    Get the monthly interest rate for a debt instrument.
    
    Returns:
        float: Monthly rate (APR / 12)
    """
    apr_schedule = debt.get("apr_schedule", {})
    apr = _get_rate_for_date(apr_schedule, current_date)
    return apr / 12.0


def min_payment(debt, current_balance):
    """
    Calculate minimum payment for a debt based on its payment rule.
    
    Returns:
        float: Minimum payment amount
    """
    min_payment_rule = debt.get("min_payment_rule", {})
    rule_type = min_payment_rule.get("type", "fixed")
    
    if rule_type == "fixed":
        return float(min_payment_rule.get("amount", 0))
    elif rule_type == "percent":
        rate = float(min_payment_rule.get("rate", 0))
        return current_balance * rate
    elif rule_type == "amortizing":
        # TODO: Implement amortizing payment calculation
        return float(min_payment_rule.get("amount", 0))
    return 0.0


# ============================================================================
# Step B: Simulation loop
# ============================================================================

def simulate(config, start_date=None, months=None, cash_account_name=None, stop_mode="debt"):
    """
    Simulate month-by-month with multiple accounts, debts, income, and expenses.
    
    Order of operations each month:
    1. Compute income + expenses
    2. Update cash account: cash += income - expenses
    3. Apply cash interest (HYSA)
    4. Apply debt interest (per debt)
    5. Apply payments (simple allocator - single debt gets all payments for now)
    6. Log
    
    Args:
        config: Configuration dictionary
        start_date: Start date for simulation (defaults to config or today)
        months: Maximum months to simulate (defaults to config or 120)
        cash_account_name: Name of cash account (defaults to config or "HYSA")
        stop_mode: One of:
            - "fixed": Run for full duration (don't stop early)
            - "debt": Stop when all debts are paid off
            - "goal": Stop when net worth goal is reached
    
    Returns list of monthly records with full financial snapshot.
    """
    # Get simulation parameters (from config or function args)
    sim_cfg = config.get("simulation", {})
    start_date = start_date or sim_cfg.get("start_date", date.today())
    months = months or sim_cfg.get("months", 120)
    cash_account_name = cash_account_name or sim_cfg.get("cash_account", "HYSA")
    goal_net_worth = sim_cfg.get("goal_net_worth", None)
    investing_account = sim_cfg.get("investing_account")
    
    instruments = config.get("instruments", {})
    accounts = instruments.get("accounts", [])
    debts = instruments.get("debts", [])
    
    # Get cash account
    cash_account = get_account(config, cash_account_name)
    if not cash_account:
        raise ValueError(f"Cash account '{cash_account_name}' not found in accounts")
    
    # Initialize balances
    account_balances = {acc["name"]: float(acc["balance"]) for acc in accounts}
    debt_balances = {debt["name"]: float(debt["balance"]) for debt in debts}
    
    # Legacy payment guess (for backward compatibility)
    payment_guess = config.get("payment_guess", 0.0)
    
    records = []
    current = start_date
    
    for _ in range(months):
        # Check debt-based stopping condition at start of month
        if stop_mode == "debt":
            # Stop when all debts are paid off
            if all(balance <= 0 for balance in debt_balances.values()):
                break
        
        # Snapshot starting balances
        month_start_accounts = account_balances.copy()
        month_start_debts = debt_balances.copy()
        
        # 1. Compute income + expenses
        income_total, expense_total = get_monthly_cashflows(config, current)
        
        # 2. Update cash account: cash += income - expenses
        account_balances[cash_account_name] += income_total - expense_total
        
        # 2b. Optional monthly investing: transfer from cash to investing account
        investing_account = sim_cfg.get("investing_account")
        if investing_account and investing_account in account_balances:
            monthly_investing = sim_cfg.get("monthly_investing") or 0
            monthly_investing_pct = sim_cfg.get("monthly_investing_pct") or 0
            if monthly_investing_pct > 0:
                amount = income_total * (monthly_investing_pct / 100.0)
            else:
                amount = monthly_investing
            if amount > 0:
                cash_available = max(0.0, account_balances[cash_account_name])
                transfer = min(amount, cash_available)
                if transfer > 0:
                    account_balances[cash_account_name] -= transfer
                    account_balances[investing_account] += transfer
        
        # 3. Apply cash interest (HYSA and other accounts)
        account_interest = {}
        for acc in accounts:
            acc_name = acc["name"]
            balance = account_balances[acc_name]
            if balance > 0:
                rate_schedule = acc.get("rate_schedule", 0)
                rate = _get_rate_for_date(rate_schedule, current)
                monthly_rate = rate / 12.0
                interest = balance * monthly_rate
                account_balances[acc_name] += interest
                account_interest[acc_name] = interest
        
        # 4. Apply debt interest (per debt)
        debt_interest = {}
        for debt in debts:
            debt_name = debt["name"]
            balance = debt_balances[debt_name]
            if balance > 0:
                monthly_rate = debt_monthly_rate(debt, current)
                interest = balance * monthly_rate
                debt_balances[debt_name] += interest
                debt_interest[debt_name] = interest
        
        # 5. Apply payments (simple allocator - single debt gets all payments for now)
        payments = {}
        cash_available = max(0.0, account_balances[cash_account_name])
        
        # Simple allocator: find first debt with balance > 0, allocate payment_guess to it
        for debt in debts:
            debt_name = debt["name"]
            balance = debt_balances[debt_name]
            if balance <= 0:
                payments[debt_name] = 0.0
                continue
            
            # Calculate payment: max(min_payment, payment_guess), capped by balance and cash
            min_pay = min_payment(debt, balance)
            target_payment = max(min_pay, payment_guess)
            payment = min(target_payment, balance, cash_available)
            
            payments[debt_name] = payment
            debt_balances[debt_name] -= payment
            account_balances[cash_account_name] -= payment
            cash_available -= payment
            
            # Simple allocator: only pay one debt per month (first one found)
            break
        
        # 6. Log
        total_accounts = sum(account_balances.values())
        total_debts = sum(debt_balances.values())
        net_worth = total_accounts - total_debts
        total_payments = sum(payments.values())
        monthly_surplus = income_total - expense_total - total_payments
        
        # Check goal-based stopping condition after net worth is calculated
        if stop_mode == "goal":
            if goal_net_worth is not None and net_worth >= goal_net_worth:
                # Record this month before breaking
                records.append({
                    "date": current,
                    "accounts": {name: round(bal, 2) for name, bal in account_balances.items()},
                    "debts": {name: round(bal, 2) for name, bal in debt_balances.items()},
                    "accounts_start": {name: round(bal, 2) for name, bal in month_start_accounts.items()},
                    "debts_start": {name: round(bal, 2) for name, bal in month_start_debts.items()},
                    "income": round(income_total, 2),
                    "expenses": round(expense_total, 2),
                    "payments": {name: round(amt, 2) for name, amt in payments.items()},
                    "account_interest": {name: round(amt, 2) for name, amt in account_interest.items()},
                    "debt_interest": {name: round(amt, 2) for name, amt in debt_interest.items()},
                    "total_accounts": round(total_accounts, 2),
                    "total_debts": round(total_debts, 2),
                    "net_worth": round(net_worth, 2),
                    "monthly_surplus": round(monthly_surplus, 2),
                })
                break
        
        records.append({
            "date": current,
            "accounts": {name: round(bal, 2) for name, bal in account_balances.items()},
            "debts": {name: round(bal, 2) for name, bal in debt_balances.items()},
            "accounts_start": {name: round(bal, 2) for name, bal in month_start_accounts.items()},
            "debts_start": {name: round(bal, 2) for name, bal in month_start_debts.items()},
            "income": round(income_total, 2),
            "expenses": round(expense_total, 2),
            "payments": {name: round(amt, 2) for name, amt in payments.items()},
            "account_interest": {name: round(amt, 2) for name, amt in account_interest.items()},
            "debt_interest": {name: round(amt, 2) for name, amt in debt_interest.items()},
            "total_accounts": round(total_accounts, 2),
            "total_debts": round(total_debts, 2),
            "net_worth": round(net_worth, 2),
            "monthly_surplus": round(monthly_surplus, 2),
        })
        
        current = _add_months(current, 1)
    
    return records
