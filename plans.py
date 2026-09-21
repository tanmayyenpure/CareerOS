"""
plans.py — single source of truth for CareerOS pricing & plan limits.
Amounts are in paise (Razorpay requires the smallest currency unit).
Drop this file next to app.py.
"""

PLANS = {
    "free": {
        "name": "Free",
        "monthly_paise": 0,
        "yearly_paise": 0,
    },
    "pro": {
        "name": "Pro",
        "monthly_paise": 49900,       # ₹499
        "yearly_paise": 418800,       # ₹4,188/yr (~30% off)
    },
    "team": {
        "name": "Team",
        "monthly_paise": 199900,      # ₹1,999
        "yearly_paise": 1678800,      # ₹16,788/yr
        "seats": 10,
    },
}

VALID_PLAN_IDS = {"pro", "team"}          # "free" is never purchased
VALID_CYCLES = {"monthly", "yearly"}


def get_amount_paise(plan_id: str, cycle: str) -> int:
    if plan_id not in VALID_PLAN_IDS or cycle not in VALID_CYCLES:
        raise ValueError(f"Invalid plan/cycle: {plan_id}/{cycle}")
    key = "monthly_paise" if cycle == "monthly" else "yearly_paise"
    return PLANS[plan_id][key]
