"""
Agentic layer for fin-os.

Wraps the deterministic simulation engine as a set of tools and drives an
agentic loop with Claude (claude-opus-4-8). The agent can:

  - run_simulation     : run / re-run the simulation with what-if overrides
  - update_scenario    : build or edit the scenario from natural language
  - compare_strategies : sweep several strategies and rank them (goal optimizer)

The engine itself stays pure and untouched — this module only orchestrates it
and talks to the model. State (the working scenario + conversation history) is
held in an AgentSession, which the web layer keeps per server process.
"""
import copy
import json
from datetime import date

import anthropic

from config import CONFIG
from engine import simulate, get_monthly_cashflows
from scenario import build_scenario

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

# Assumed annual return for an investment account we create on the fly when the
# user asks to invest but has no brokerage in their scenario. The agent is told
# to surface this assumption.
DEFAULT_INVEST_RETURN = 0.07


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

def _account_kind(acc):
    return (acc.get("kind") or acc.get("type") or "cash").strip().lower()


def _is_investment(acc):
    return _account_kind(acc) in ("invest", "investment")


def _ensure_investment_account(config):
    """Return the first investment account, creating an 'Investments' one if none."""
    accounts = config["instruments"]["accounts"]
    for a in accounts:
        if _is_investment(a):
            return a
    acc = {
        "name": "Investments",
        "balance": 0.0,
        "kind": "investment",
        "annual_return": DEFAULT_INVEST_RETURN,
        "monthly_target": 0.0,
    }
    accounts.append(acc)
    return acc


def _fmt_money(x):
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _annual_rate(schedule_or_num, when):
    """Resolve an APR/APY value (number or promo schedule dict) for a date."""
    if isinstance(schedule_or_num, dict):
        if schedule_or_num.get("promo_end") and when and when < schedule_or_num["promo_end"]:
            return float(schedule_or_num.get("promo_apr", 0))
        return float(schedule_or_num.get("standard_apr", 0))
    try:
        return float(schedule_or_num or 0)
    except (TypeError, ValueError):
        return 0.0


def scenario_text(config):
    """Human-readable snapshot of the current scenario for the system prompt."""
    sim = config.get("simulation", {})
    start = sim.get("start_date") or date.today()
    instruments = config.get("instruments", {})
    streams = config.get("cashflow_streams", {})

    lines = []
    lines.append("ACCOUNTS:")
    for a in instruments.get("accounts", []):
        kind = "investment" if _is_investment(a) else "cash"
        ar = a.get("annual_return")
        if ar is None:
            ar = _annual_rate(a.get("rate_schedule", 0), start)
        bits = [f"  - {a.get('name')}: {_fmt_money(a.get('balance', 0))}", f"{kind}", f"return {float(ar):.2%}"]
        if a.get("monthly_target"):
            bits.append(f"monthly_target {_fmt_money(a['monthly_target'])}")
        lines.append(", ".join(bits))
    if not instruments.get("accounts"):
        lines.append("  (none)")

    lines.append("DEBTS:")
    for d in instruments.get("debts", []):
        apr = _annual_rate(d.get("apr_schedule", 0), start)
        rule = d.get("min_payment_rule") or {}
        if (rule.get("type") or "fixed") == "percent":
            minp = f"{float(rule.get('rate', 0)):.2%} of balance"
        else:
            minp = _fmt_money(rule.get("amount", 0))
        sched = d.get("apr_schedule")
        promo = ""
        if isinstance(sched, dict) and sched.get("promo_end"):
            promo = f", promo {float(sched.get('promo_apr', 0)):.2%} until {sched['promo_end']} then {float(sched.get('standard_apr', 0)):.2%}"
        lines.append(f"  - {d.get('name')}: {_fmt_money(d.get('balance', 0))}, APR {apr:.2%}{promo}, min payment {minp}")
    if not instruments.get("debts", []):
        lines.append("  (no debts)")

    inc = streams.get("income", [])
    exp = streams.get("expenses", [])
    lines.append("INCOME:")
    for i in inc:
        lines.append(f"  - {i.get('name')}: {_fmt_money(i.get('amount', 0))} / {i.get('cadence', 'monthly')}")
    lines.append("EXPENSES:")
    for e in exp:
        lines.append(f"  - {e.get('name')}: {_fmt_money(e.get('amount', 0))} / {e.get('cadence', 'monthly')}")

    income_total, expense_total = get_monthly_cashflows(config, start)
    lines.append("SETTINGS:")
    lines.append(f"  - start_date: {start}")
    lines.append(f"  - cash_landing_account: {sim.get('cash_landing_account') or sim.get('cash_account')}")
    lines.append(f"  - emergency_floor: {_fmt_money(sim.get('emergency_floor', 0))}")
    lines.append(f"  - goal_net_worth: {_fmt_money(sim.get('goal_net_worth')) if sim.get('goal_net_worth') else '(none)'}")
    lines.append(f"  - monthly income ≈ {_fmt_money(income_total)}, monthly expenses ≈ {_fmt_money(expense_total)}, surplus ≈ {_fmt_money(income_total - expense_total)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Simulation + summarization
# ---------------------------------------------------------------------------

def _summarize_records(records, config):
    """Compact, model-friendly summary plus a chart-friendly trajectory."""
    if not records:
        return {"error": "No simulation steps — check that the scenario has debts and/or income."}, None

    first, last = records[0], records[-1]
    start_accounts = sum(first["accounts_start"].values())
    start_debts = sum(first["debts_start"].values())
    start_nw = start_accounts - start_debts

    total_paid = sum(sum(r["payments"].values()) for r in records)
    total_contrib = sum(sum(r.get("contributions", {}).values()) for r in records)
    total_debt_interest = sum(sum(r.get("debt_interest", {}).values()) for r in records)
    total_income = sum(r["income"] for r in records)
    total_expenses = sum(r["expenses"] for r in records)

    debt_paid_off = next((r["date"] for r in records if r["total_debts"] <= 0.01), None)
    goal = config.get("simulation", {}).get("goal_net_worth")
    goal_reached = next((r["date"] for r in records if goal and r["net_worth"] >= goal), None)

    rates = [(r["income"] - r["expenses"]) / r["income"] for r in records if r["income"] > 0]
    savings_rate = sum(rates) / len(rates) if rates else 0.0

    summary = {
        "months_simulated": len(records),
        "start_net_worth": round(start_nw, 2),
        "final_net_worth": round(last["net_worth"], 2),
        "final_accounts_total": round(last["total_accounts"], 2),
        "final_debts_total": round(last["total_debts"], 2),
        "final_account_balances": last["accounts"],
        "final_debt_balances": last["debts"],
        "total_debt_payments": round(total_paid, 2),
        "total_invested": round(total_contrib, 2),
        "total_debt_interest_paid": round(total_debt_interest, 2),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "avg_savings_rate": round(savings_rate, 4),
        "debt_paid_off_month": debt_paid_off.strftime("%Y-%m") if debt_paid_off else None,
        "all_debt_cleared": bool(debt_paid_off),
        "goal_net_worth": goal,
        "goal_reached_month": goal_reached.strftime("%Y-%m") if goal_reached else None,
    }

    # Trajectory for charting (one point per month) + a downsampled version for the model.
    trajectory = [
        {
            "month": r["date"].strftime("%Y-%m"),
            "net_worth": round(r["net_worth"], 2),
            "accounts": round(r["total_accounts"], 2),
            "debts": round(r["total_debts"], 2),
        }
        for r in records
    ]
    step = max(1, len(trajectory) // 12)
    summary["net_worth_trajectory"] = trajectory[::step]
    if trajectory[-1] not in summary["net_worth_trajectory"]:
        summary["net_worth_trajectory"].append(trajectory[-1])

    chart = {
        "labels": [p["month"] for p in trajectory],
        "net_worth": [p["net_worth"] for p in trajectory],
        "debts": [p["debts"] for p in trajectory],
        "accounts": [p["accounts"] for p in trajectory],
        "goal": goal,
        "summary": {
            "final_net_worth": summary["final_net_worth"],
            "debt_paid_off_month": summary["debt_paid_off_month"],
            "months_simulated": summary["months_simulated"],
            "total_invested": summary["total_invested"],
            "avg_savings_rate": summary["avg_savings_rate"],
            "final_debts_total": summary["final_debts_total"],
            "total_debt_interest_paid": summary["total_debt_interest_paid"],
        },
    }
    return summary, chart


def _config_with_overrides(base_config, overrides):
    """Return a deep copy of base_config with what-if overrides applied (non-destructive)."""
    config = copy.deepcopy(base_config)
    sim = config.setdefault("simulation", {})
    overrides = overrides or {}

    if overrides.get("emergency_floor") is not None:
        sim["emergency_floor"] = float(overrides["emergency_floor"])
    if overrides.get("goal_net_worth") is not None:
        sim["goal_net_worth"] = float(overrides["goal_net_worth"])

    monthly_investing = overrides.get("monthly_investing")
    monthly_investing_pct = overrides.get("monthly_investing_pct")
    if monthly_investing or monthly_investing_pct:
        acc = _ensure_investment_account(config)
        if monthly_investing:
            acc["monthly_target"] = float(monthly_investing)
        else:
            income_total, _ = get_monthly_cashflows(config, sim.get("start_date") or date.today())
            acc["monthly_target"] = income_total * float(monthly_investing_pct) / 100.0

    # Per-expense adjustments: {"Rent": 900, "Gym": 0}
    for name, amount in (overrides.get("expense_overrides") or {}).items():
        for e in config.get("cashflow_streams", {}).get("expenses", []):
            if (e.get("name") or "").strip().lower() == str(name).strip().lower():
                e["amount"] = float(amount)
                break
    return config


def _run(config, overrides):
    overrides = overrides or {}
    merged = _config_with_overrides(config, overrides)
    sim = merged.get("simulation", {})
    months = int(overrides.get("months") or sim.get("months") or 120)
    stop_mode = overrides.get("stop_mode") or "debt"
    if stop_mode not in ("debt", "goal", "fixed"):
        stop_mode = "debt"
    records = simulate(merged, sim.get("start_date"), months, stop_mode=stop_mode)
    return _summarize_records(records, merged)


# ---------------------------------------------------------------------------
# Tool definitions + dispatch
# ---------------------------------------------------------------------------

_OVERRIDE_PROPS = {
    "months": {"type": "integer", "description": "Max months to simulate (default 120)."},
    "stop_mode": {
        "type": "string",
        "enum": ["debt", "goal", "fixed"],
        "description": "'debt' = stop when all debt is paid; 'goal' = stop when goal_net_worth reached; 'fixed' = run the full months.",
    },
    "emergency_floor": {"type": "number", "description": "Minimum cash to keep in the landing account before any extra debt payoff/investing."},
    "monthly_investing": {"type": "number", "description": "Fixed $/month to route into an investment account (created if none exists)."},
    "monthly_investing_pct": {"type": "number", "description": "Percent of monthly income to invest (0-100). Used if monthly_investing is not set."},
    "goal_net_worth": {"type": "number", "description": "Net-worth target (used with stop_mode 'goal')."},
    "expense_overrides": {
        "type": "object",
        "description": "Map of expense name -> new monthly amount, e.g. {\"Rent\": 900}. Set to 0 to drop an expense.",
        "additionalProperties": {"type": "number"},
    },
}

TOOLS = [
    {
        "name": "run_simulation",
        "description": (
            "Run the month-by-month financial simulation on the current scenario, optionally with "
            "what-if overrides (extra investing, different emergency floor, changed expenses, a goal, etc.). "
            "Overrides are NOT saved to the scenario — they apply only to this run. Returns final net worth, "
            "debt payoff month, total interest paid, savings rate, and a net-worth trajectory. "
            "Call this whenever the user asks what would happen, how long something takes, or to compare a single change."
        ),
        "input_schema": {"type": "object", "properties": dict(_OVERRIDE_PROPS), "additionalProperties": False},
    },
    {
        "name": "compare_strategies",
        "description": (
            "Run several named strategies in one shot and get a summary for each, so you can rank them. "
            "Use this for optimization questions ('fastest way to be debt-free', 'best split between debt and investing'). "
            "Each variant has a name and the same override fields as run_simulation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "variants": {
                    "type": "array",
                    "description": "List of strategies to simulate and compare.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Short label for this strategy."},
                            **_OVERRIDE_PROPS,
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["variants"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_scenario",
        "description": (
            "Create or edit the working scenario. Pass the FULL lists you want the scenario to have "
            "(accounts, debts, income, expenses) — they replace the current ones. To edit one item, include "
            "all items with that one changed. Use this when the user describes their finances in natural language "
            "or asks to change a balance, rate, income, or expense. After updating, you usually want to run_simulation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "accounts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "balance": {"type": "number"},
                            "rate_schedule": {"type": "number", "description": "Annual return / APY as a decimal, e.g. 0.042 for 4.2%."},
                            "type": {"type": "string", "enum": ["cash", "invest"], "description": "'cash' for savings/checking/HYSA, 'invest' for brokerage/retirement."},
                        },
                        "required": ["name", "balance", "type"],
                        "additionalProperties": False,
                    },
                },
                "debts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "balance": {"type": "number"},
                            "apr": {"type": "number", "description": "Annual interest rate as a decimal, e.g. 0.2249 for 22.49%."},
                            "min_payment": {"type": "number", "description": "Fixed minimum monthly payment in dollars."},
                        },
                        "required": ["name", "balance", "apr"],
                        "additionalProperties": False,
                    },
                },
                "income": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "amount": {"type": "number"},
                            "cadence": {"type": "string", "enum": ["monthly", "biweekly"]},
                        },
                        "required": ["name", "amount"],
                        "additionalProperties": False,
                    },
                },
                "expenses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "amount": {"type": "number"},
                            "cadence": {"type": "string", "enum": ["monthly", "biweekly"]},
                        },
                        "required": ["name", "amount"],
                        "additionalProperties": False,
                    },
                },
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD for the simulation start."},
                "goal_net_worth": {"type": "number"},
                "emergency_floor": {"type": "number"},
                "cash_account": {"type": "string", "description": "Name of the cash account where income lands."},
            },
            "additionalProperties": False,
        },
    },
]


def _tool_update_scenario(session, args):
    """Rebuild the working scenario from supplied lists, keeping current values for anything omitted."""
    cur = session.config
    cur_sim = cur.get("simulation", {})
    streams = cur.get("cashflow_streams", {})
    instruments = cur.get("instruments", {})

    # Default to current values so partial updates don't wipe the scenario.
    accounts = args.get("accounts")
    if accounts is None:
        accounts = [
            {
                "name": a.get("name"),
                "balance": a.get("balance", 0),
                "rate_schedule": a.get("annual_return", a.get("rate_schedule", 0)),
                "type": "invest" if _is_investment(a) else "cash",
            }
            for a in instruments.get("accounts", [])
        ]

    debts = args.get("debts")
    if debts is None:
        debts = []
        for d in instruments.get("debts", []):
            rule = d.get("min_payment_rule") or {}
            debts.append({
                "name": d.get("name"),
                "balance": d.get("balance", 0),
                "apr": _annual_rate(d.get("apr_schedule", 0), cur_sim.get("start_date") or date.today()),
                "min_payment": rule.get("amount", 0),
            })
    else:
        debts = [
            {
                "name": d.get("name"),
                "balance": d.get("balance", 0),
                "apr_schedule": d.get("apr", 0),
                "min_payment_rule": {"type": "fixed", "amount": d.get("min_payment", 0)},
            }
            for d in debts
        ]

    income = args.get("income")
    if income is None:
        income = [dict(i) for i in streams.get("income", [])]
    expenses = args.get("expenses")
    if expenses is None:
        expenses = [dict(e) for e in streams.get("expenses", [])]

    start_date = args.get("start_date") or cur_sim.get("start_date") or date.today()
    goal = args.get("goal_net_worth", cur_sim.get("goal_net_worth"))
    cash_account = args.get("cash_account") or cur_sim.get("cash_landing_account") or cur_sim.get("cash_account")
    months = cur_sim.get("months", 120)

    new_config = build_scenario(
        accounts=accounts,
        debts=debts,
        income=income,
        expenses=expenses,
        start_date=start_date,
        months=months,
        cash_account=cash_account,
        goal_net_worth=goal,
    )
    if args.get("emergency_floor") is not None:
        new_config["simulation"]["emergency_floor"] = float(args["emergency_floor"])
    else:
        new_config["simulation"]["emergency_floor"] = cur_sim.get("emergency_floor", 0)

    session.config = new_config
    return {"ok": True, "scenario": scenario_text(new_config)}, None


def dispatch_tool(session, name, args):
    """Execute a tool. Returns (result_for_model: dict, chart_data_or_None)."""
    try:
        if name == "run_simulation":
            return _run(session.config, args)
        if name == "compare_strategies":
            results = []
            last_chart = None
            for variant in args.get("variants", []):
                label = variant.get("name", "strategy")
                overrides = {k: v for k, v in variant.items() if k != "name"}
                summary, chart = _run(session.config, overrides)
                summary["strategy"] = label
                summary.pop("net_worth_trajectory", None)  # keep the comparison compact
                results.append(summary)
                if chart is not None:
                    last_chart = chart
            return {"strategies": results}, last_chart
        if name == "update_scenario":
            return _tool_update_scenario(session, args)
        return {"error": f"Unknown tool: {name}"}, None
    except Exception as e:  # surface tool failures to the model rather than crashing the loop
        return {"error": f"{type(e).__name__}: {e}"}, None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PREAMBLE = """You are the agent inside fin-os, a personal budgeting and debt/net-worth planner.

You help one person (the user) reason about their money: paying down debt, building savings, \
investing, and reaching net-worth goals. You have direct access to a deterministic simulation \
engine through tools — USE IT. Never estimate trajectories in your head when you can simulate them.

How the engine works each month: income lands in the cash account, expenses come out, accounts earn \
their return, debts accrue interest, then an allocation policy pays debt minimums, keeps the emergency \
floor, funds investment monthly_targets, and throws any remaining surplus at the highest-APR debt \
(avalanche) — or into investments once debts are clear.

Working style:
- When the user asks "what if", "how long", "can I", or "should I", call run_simulation (or \
compare_strategies for ranking several options). Ground every quantitative claim in a tool result.
- When the user describes their finances in words, or asks to change a number, call update_scenario.
- State your assumptions plainly — especially investment returns. If you create an investment account \
to model investing, it assumes a {invest_return:.0%} annual return; say so.
- Lead with the answer: the number or recommendation first, then the brief reasoning. Use compact \
markdown. Don't dump raw tool JSON — interpret it.
- For minor modeling choices, pick a sensible default and note it rather than asking. Ask only when a \
real decision is the user's to make.
- You are a planning tool, not a licensed advisor; keep guidance practical and note when something \
warrants professional/tax advice.

The user's current scenario (regenerated each turn — always current):

{scenario}
"""


def build_system_prompt(config):
    return SYSTEM_PREAMBLE.format(scenario=scenario_text(config), invest_return=DEFAULT_INVEST_RETURN)


# ---------------------------------------------------------------------------
# Session + agentic loop
# ---------------------------------------------------------------------------

class AgentSession:
    """Holds the working scenario and conversation history for one chat session."""

    def __init__(self, config=None):
        self.config = copy.deepcopy(config or CONFIG)
        self.messages = []
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def reset(self, config=None):
        self.config = copy.deepcopy(config or CONFIG)
        self.messages = []

    def _open_stream(self, system):
        """Open a streaming request. Adaptive thinking is used when the installed
        SDK supports the `thinking` argument; older SDKs gracefully omit it."""
        kwargs = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=self.messages,
        )
        try:
            return self.client.messages.stream(thinking={"type": "adaptive"}, **kwargs)
        except TypeError as e:
            if "thinking" not in str(e):
                raise
            return self.client.messages.stream(**kwargs)

    def stream_chat(self, user_message):
        """Run one user turn through the agentic loop.

        Yields event dicts:
          {"type": "text", "text": ...}          incremental assistant text
          {"type": "tool", "name": ...}          a tool is being called
          {"type": "simulation", "data": {...}}  chart data from a simulation
          {"type": "scenario", "text": ...}       the scenario changed
          {"type": "done"} | {"type": "error", "message": ...}
        """
        self.messages.append({"role": "user", "content": user_message})
        try:
            try:
                client = self.client
                has_creds = getattr(client, "api_key", None) or getattr(client, "auth_token", None)
            except Exception:
                has_creds = False
            if not has_creds:
                yield {"type": "error", "message": (
                    "No Claude credentials found. Set ANTHROPIC_API_KEY in your environment "
                    "(or run `ant auth login`) and restart the server."
                )}
                return
            while True:
                system = build_system_prompt(self.config)
                with self._open_stream(system) as stream:
                    for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            yield {"type": "text", "text": event.delta.text}
                    final = stream.get_final_message()

                self.messages.append({"role": "assistant", "content": final.content})

                if final.stop_reason != "tool_use":
                    break

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    yield {"type": "tool", "name": block.name}
                    result, chart = dispatch_tool(self, block.name, block.input or {})
                    if chart is not None:
                        yield {"type": "simulation", "data": chart}
                    if block.name == "update_scenario" and isinstance(result, dict) and result.get("ok"):
                        yield {"type": "scenario", "text": result.get("scenario", "")}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                self.messages.append({"role": "user", "content": tool_results})

            yield {"type": "done"}
        except anthropic.AuthenticationError:
            yield {"type": "error", "message": "Authentication failed. Set ANTHROPIC_API_KEY in your environment."}
        except anthropic.APIError as e:
            yield {"type": "error", "message": f"Claude API error: {getattr(e, 'message', str(e))}"}
        except Exception as e:
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
