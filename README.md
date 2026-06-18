# fin-os
<<<<<<< HEAD

Financial simulation and planning tool.

## Quick Start

### Command Line Usage

```bash
# Run until debt is paid off (default)
python finos/run.py

# Run until net worth goal is reached
python finos/run.py --until-goal

# Run for fixed 12 months
python finos/run.py --months 12

# Show results in web browser
python finos/run.py --until-goal --web

# Show monthly table in web view
python finos/run.py --until-goal --web --show-table
```

### Web Interface

**Interactive scenario builder** – Enter your own accounts, debts, income, and expenses in the browser, then run the simulation:

```bash
python finos/run.py --web-app
```

Then open `http://localhost:3000`, fill in the form, choose how to run (until debt paid / until goal / fixed months), and click **Run simulation**.

**Pre-run simulation, then view in browser** – Use config from `finos/config.py` and show results in the browser:

```bash
python finos/run.py --until-goal --web
```

The server runs on `http://localhost:3000` by default. Use `--port 8080` to use a different port.

The web interface provides:
- Scenario form: accounts, debts, income, expenses, goal net worth, extra payment
- Run options: **Run until debt paid off**, **Run until goal net worth**, **Run for N months**
- Clean, readable financial summaries and optional monthly detail table
- Status badges for goals and debt payoff

Press `Ctrl+C` to stop the web server.

### 🤖 Agentic advisor (chat)

Talk to a financial advisor that **drives the simulation engine for you**. Claude has the
engine wired up as tools — it runs and re-runs simulations, tries what-ifs, compares
strategies, and can set up or edit your scenario from a plain-English description. Every
number it gives you is grounded in an actual simulation, not guessed.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or: ant auth login
python finos/run.py --agent
```

Then open `http://localhost:3000` and ask things like:

- *"When am I debt-free at my current pace?"*
- *"If I invest $500/mo, what's my net worth in 5 years?"*
- *"What's the fastest way to be debt-free?"* (it compares strategies and ranks them)
- *"I make $5,600/mo, rent is $850, and I have $5,800 on a card at 22% APR…"* (it builds your scenario)

The right-hand panel shows a live net-worth/debt chart that updates each time the agent
runs a simulation, plus your current scenario.

**It's a persistent, multi-scenario platform.** Your plans and conversations are saved to a
local SQLite database (`~/.fin-os/finos.db`, override with `FINOS_DB`), so they survive
restarts. Use the left sidebar to keep multiple named plans — *"Current path"*, *"If I move
to NYC"*, *"Aggressive payoff"* — each with its own numbers and chat. Creating a plan forks
the active one's numbers so you can tweak and compare. Switch, rename, and delete from the
sidebar; the agent edits whichever plan is active.

**Compare two plans side by side.** The ⇄ button (top of the insights panel) opens a compare view:
pick any two plans and see their net-worth curves overlaid, a metric table with deltas (final net
worth, debt-free date, total invested, savings rate, interest paid), and a precise diff of exactly
what's different between the two scenarios. Both plans are simulated over the same fixed horizon so
the curves line up.

**Edit your numbers directly.** The **Edit ✎** link on the scenario panel opens a form to add,
change, or remove accounts, debts, income, expenses, and settings — no chat required. Changes save
to the active plan and are picked up by the agent on its next reply. Editing a debt's APR leaves its
promo schedule intact unless you actually change the rate.

The agent uses Claude (`claude-opus-4-8`) via the official `anthropic` SDK. It runs locally;
your scenario and conversation never leave your machine except as prompts to the Claude API.

**Capabilities** (agent tools, in `finos/agent.py`):
- `run_simulation` — run/re-run with what-if overrides (investing, emergency floor, expenses, goal)
- `compare_strategies` — sweep several strategies in one shot and rank them
- `update_scenario` — create or edit your accounts, debts, income, and expenses from natural language

### Building a scenario in code

Use `build_scenario()` to build an engine-compatible config from user inputs (e.g. from your own UI or API):

```python
from finos.scenario import build_scenario
from finos.engine import simulate

config = build_scenario(
    accounts=[{"name": "HYSA", "balance": 3000, "rate_schedule": 0.042}],
    debts=[{"name": "Credit Card", "balance": 5000, "apr_schedule": 0.22, "min_payment_rule": {"type": "fixed", "amount": 35}}],
    income=[{"name": "Salary", "amount": 5500, "cadence": "monthly"}],
    expenses=[{"name": "Rent", "amount": 1200, "cadence": "monthly"}],
    start_date="2026-02-24",
    goal_net_worth=100_000,
    payment_guess=300,
)
records = simulate(config, config["simulation"]["start_date"], 120, stop_mode="goal")
```
what if you knew everything about your money?
=======
what if i knew where my money was going before i even spent it?

this project builds on my own experiences with debt consolidation, credit cardmaxxing and my own interest in building net worth fast while still maximizing my lifestyle.
>>>>>>> 5fa27ddb8eabc10d4b95d413ebd539627217fb82
