from datetime import date

CONFIG = {
    "debt": {
        "balance": 5815.00,
        "promo_apr": 0.00,
        "standard_apr": 0.2249,
        "promo_end": date(2027, 8, 1),
        "min_payment": 35.00,
    },
    "cash": {
        "balance": 2000.00,
        "hysa_rate": 0.042,
    },
    "monthly": {
        "income": 5500.00,
        "spend": 700.00,
        "payment_guess": 320.00,
    }
}