"""
Compare two scenarios side by side.

Produces a structured, human-readable diff of what's different between two
engine configs (accounts, debts, income, expenses, settings). Simulation of
each plan is delegated to the agent's runner so both views use the exact same
month-by-month engine and summary.
"""
from datetime import date

from agent import _run, _annual_rate, _fmt_money, _is_investment


def _pct(x):
    try:
        return f"{float(x):.2%}"
    except (TypeError, ValueError):
        return str(x)


def _by_name(items):
    out = {}
    for it in items or []:
        name = (it.get("name") or "").strip()
        if name:
            out[name] = it
    return out


def _ordered_names(a_map, b_map):
    # preserve a's order, then append b-only names
    names = list(a_map.keys())
    for n in b_map:
        if n not in a_map:
            names.append(n)
    return names


def diff_scenarios(cfg_a, cfg_b):
    """Return a list of {section, label, a, b} rows where the two configs differ."""
    rows = []

    def add(section, label, va, vb):
        if str(va) != str(vb):
            rows.append({"section": section, "label": label, "a": va, "b": vb})

    when_a = cfg_a.get("simulation", {}).get("start_date") or date.today()
    when_b = cfg_b.get("simulation", {}).get("start_date") or date.today()

    # Accounts
    aa = _by_name(cfg_a.get("instruments", {}).get("accounts", []))
    ba = _by_name(cfg_b.get("instruments", {}).get("accounts", []))
    for name in _ordered_names(aa, ba):
        x, y = aa.get(name), ba.get(name)
        if not y:
            add("Accounts", name, _fmt_money(x.get("balance", 0)), "— (not present)")
            continue
        if not x:
            add("Accounts", name, "— (not present)", _fmt_money(y.get("balance", 0)))
            continue
        add("Accounts", f"{name} · balance", _fmt_money(x.get("balance", 0)), _fmt_money(y.get("balance", 0)))
        rx = x.get("annual_return", _annual_rate(x.get("rate_schedule", 0), when_a))
        ry = y.get("annual_return", _annual_rate(y.get("rate_schedule", 0), when_b))
        add("Accounts", f"{name} · return", _pct(rx), _pct(ry))
        add("Accounts", f"{name} · type", "investment" if _is_investment(x) else "cash",
            "investment" if _is_investment(y) else "cash")
        if x.get("monthly_target") or y.get("monthly_target"):
            add("Accounts", f"{name} · monthly invest", _fmt_money(x.get("monthly_target", 0)), _fmt_money(y.get("monthly_target", 0)))

    # Debts
    ad, bd = _by_name(cfg_a.get("instruments", {}).get("debts", [])), _by_name(cfg_b.get("instruments", {}).get("debts", []))
    for name in _ordered_names(ad, bd):
        x, y = ad.get(name), bd.get(name)
        if not y:
            add("Debts", name, _fmt_money(x.get("balance", 0)), "— (not present)")
            continue
        if not x:
            add("Debts", name, "— (not present)", _fmt_money(y.get("balance", 0)))
            continue
        add("Debts", f"{name} · balance", _fmt_money(x.get("balance", 0)), _fmt_money(y.get("balance", 0)))
        add("Debts", f"{name} · APR", _pct(_annual_rate(x.get("apr_schedule", 0), when_a)),
            _pct(_annual_rate(y.get("apr_schedule", 0), when_b)))
        rx = (x.get("min_payment_rule") or {}).get("amount", 0)
        ry = (y.get("min_payment_rule") or {}).get("amount", 0)
        add("Debts", f"{name} · min payment", _fmt_money(rx), _fmt_money(ry))

    # Income & expenses
    for section, key in (("Income", "income"), ("Expenses", "expenses")):
        ax = _by_name(cfg_a.get("cashflow_streams", {}).get(key, []))
        bx = _by_name(cfg_b.get("cashflow_streams", {}).get(key, []))
        for name in _ordered_names(ax, bx):
            x, y = ax.get(name), bx.get(name)
            if not y:
                add(section, name, _fmt_money(x.get("amount", 0)), "— (not present)")
            elif not x:
                add(section, name, "— (not present)", _fmt_money(y.get("amount", 0)))
            else:
                ca, cb = x.get("cadence", "monthly"), y.get("cadence", "monthly")
                la = _fmt_money(x.get("amount", 0)) + ("" if ca == "monthly" else f" /{ca}")
                lb = _fmt_money(y.get("amount", 0)) + ("" if cb == "monthly" else f" /{cb}")
                add(section, name, la, lb)

    # Settings
    sa, sb = cfg_a.get("simulation", {}), cfg_b.get("simulation", {})
    add("Settings", "Emergency floor", _fmt_money(sa.get("emergency_floor", 0)), _fmt_money(sb.get("emergency_floor", 0)))
    add("Settings", "Goal net worth",
        _fmt_money(sa.get("goal_net_worth")) if sa.get("goal_net_worth") else "(none)",
        _fmt_money(sb.get("goal_net_worth")) if sb.get("goal_net_worth") else "(none)")
    add("Settings", "Start date", str(sa.get("start_date") or "—"), str(sb.get("start_date") or "—"))
    add("Settings", "Cash account",
        sa.get("cash_landing_account") or sa.get("cash_account") or "—",
        sb.get("cash_landing_account") or sb.get("cash_account") or "—")

    return rows


def compare(cfg_a, cfg_b):
    """Simulate both configs over a common fixed horizon so the curves line up,
    and return summaries, trajectories, and the config diff."""
    months = max(
        int(cfg_a.get("simulation", {}).get("months") or 0),
        int(cfg_b.get("simulation", {}).get("months") or 0),
        60,
    )
    overrides = {"stop_mode": "fixed", "months": months}
    sum_a, chart_a = _run(cfg_a, overrides)
    sum_b, chart_b = _run(cfg_b, overrides)
    return {
        "a": {"summary": sum_a, "chart": chart_a},
        "b": {"summary": sum_b, "chart": chart_b},
        "diff": diff_scenarios(cfg_a, cfg_b),
    }
