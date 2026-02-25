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
