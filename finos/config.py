from datetime import date

CONFIG = {
    "instruments": {
        "accounts": [
            {
                "name": "HYSA",
                "balance": 2000.00,
                "rate_schedule": 0.042,  # Fixed 4.2% APY, or use dict for variable: {"promo_end": date(...), "promo_rate": 0.05, "standard_rate": 0.042}
                "type": "cash",  # "cash" or "invest"
            },
        ],
        "debts": [
            {
                "name": "Credit Card",
                "balance": 5815.00,
                "apr_schedule": {
                    "promo_end": date(2027, 8, 1),
                    "promo_apr": 0.00,
                    "standard_apr": 0.2249,
                },
                "min_payment_rule": {
                    "type": "fixed",  # "fixed", "percent", or "amortizing"
                    "amount": 35.00,  # For "fixed" type
                },
                "start_date": None,  # Optional
            },
        ],
    },
    "cashflow_streams": {
        "income": [
            {
                "name": "Salary",
                "amount": 5586.00,
                "cadence": "monthly",  # "monthly" or "biweekly"
                "start_date": None,  # Optional, e.g., date(2026, 9, 1)
                "end_date": None,  # Optional
            },
        ],
        "expenses": [
            {"name": "Rent", "amount": 850.0, "cadence": "monthly"},
            {"name": "Utilities", "amount": 75.0, "cadence": "monthly"},
            {"name": "Gym", "amount": 179.0, "cadence": "monthly"},
            {"name": "Insurance", "amount": 180.0, "cadence": "monthly"},
            {"name": "Food/Fun", "amount": 800.0, "cadence": "monthly"},
]
    },
    "simulation": {
        "start_date": date(2026, 2, 18),
        "months": 60,
        "cash_account": "HYSA",
        "goal_net_worth": 100000.00,  # Target net worth goal (can be changed)
    },
    # Legacy field for backward compatibility with engine (will be removed later)
    "payment_guess": 320.00,
}
