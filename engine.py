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


def simulate(config, start_date, months):
    """
    Simulate month-by-month: income/spend, payment (at least min), debt interest (promo vs standard APR),
    HYSA interest. Stops when debt hits zero. Monthly compounding.

    Order of operations each month:
    1. Snapshot starting debt and cash.
    2. Add income to cash.
    3. Subtract spend from cash.
    4. Apply payment to debt (amount = max(min_payment, payment_guess), capped by debt and cash).
    5. Apply debt interest (monthly compounding; promo APR if date < promo_end else standard APR).
    6. Apply HYSA interest to cash (monthly compounding).
    """
    debt_cfg = config["debt"]
    cash_cfg = config["cash"]
    monthly_cfg = config["monthly"]

    balance_debt = float(debt_cfg["balance"])
    balance_cash = float(cash_cfg["balance"])
    promo_apr = float(debt_cfg["promo_apr"])
    standard_apr = float(debt_cfg["standard_apr"])
    promo_end = debt_cfg["promo_end"]
    min_payment = float(debt_cfg["min_payment"])
    hysa_rate = float(cash_cfg["hysa_rate"])
    income = float(monthly_cfg["income"])
    spend = float(monthly_cfg["spend"])
    payment_guess = float(monthly_cfg["payment_guess"])

    records = []
    current = start_date

    for _ in range(months):
        if balance_debt <= 0:
            break

        # 1. Start of month
        month_start_debt = balance_debt
        month_start_cash = balance_cash

        # 2. Income
        balance_cash += income

        # 3. Spend
        balance_cash -= spend

        # 4. Payment: at least min_payment, capped by debt and cash
        target_payment = max(min_payment, payment_guess)
        payment = min(target_payment, balance_debt, max(0.0, balance_cash))
        balance_debt -= payment
        balance_cash -= payment

        # 5. Debt interest (monthly compounding): promo vs standard by date
        use_promo = current < promo_end
        apr = promo_apr if use_promo else standard_apr
        monthly_debt_rate = apr / 12.0
        balance_debt *= 1.0 + monthly_debt_rate

        # 6. HYSA interest (monthly compounding)
        monthly_hysa_rate = hysa_rate / 12.0
        balance_cash *= 1.0 + monthly_hysa_rate

        debt_after_payment = month_start_debt - payment

        records.append({
            "date": current,
            "debt_start": round(month_start_debt, 2),
            "cash_start": round(month_start_cash, 2),
            "income": income,
            "spend": spend,
            "payment": round(payment, 2),
            "debt_after_payment": round(debt_after_payment, 2),
            "apr_used": promo_apr if use_promo else standard_apr,
            "debt_end": round(balance_debt, 2),
            "cash_end": round(balance_cash, 2),
        })

        current = _add_months(current, 1)

    return records
