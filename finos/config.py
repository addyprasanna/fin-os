from datetime import date

CONFIG = {
    "instruments": {
        "accounts": [
            {
                "name": "HYSA",
                "balance": 3000.00,
                "kind": "cash",
                "annual_return": 0.042,
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
                "min_payment_rule": {"type": "fixed", "amount": 35.00},
                "start_date": None,
            },
        ],
    },
    "cashflow_streams": {
        "income": [
            {"name": "Salary", "amount": 5586.00, "cadence": "monthly", "start_date": None, "end_date": None},
        ],
        "expenses": [
            {"name": "Rent", "amount": 850.0, "cadence": "monthly"},
            {"name": "Utilities", "amount": 75.0, "cadence": "monthly"},
            {"name": "Gym", "amount": 179.0, "cadence": "monthly"},
            {"name": "Insurance", "amount": 180.0, "cadence": "monthly"},
            {"name": "Food/Fun", "amount": 800.0, "cadence": "monthly"},
        ],
    },
    "simulation": {
        "start_date": date(2026, 2, 18),
        "months": 60,
        "cash_landing_account": "HYSA",
        "emergency_floor": 1000.00,
        "goal_net_worth": 100000.00,
    },
}
