#!/usr/bin/env python3
"""
Simple web interface for displaying simulation results.
Serves results on localhost for easier reading.
Interactive mode: form to enter accounts/expenses and run until goal / debt paid / fixed.
"""
import json
from datetime import date
from flask import Flask, render_template_string, request
import webbrowser
import threading
import time

from scenario import build_scenario
from engine import simulate


def _config_to_json_safe(config):
    """Serialize config for scenario_json: dates → ISO strings."""
    sim = dict(config.get("simulation", {}))
    sd = sim.get("start_date")
    if sd is not None:
        sim["start_date"] = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
    out = json.loads(json.dumps({
        "instruments": config.get("instruments", {}),
        "cashflow_streams": config.get("cashflow_streams", {}),
        "simulation": sim,
        "payment_guess": config.get("payment_guess", 0),
    }, default=str))
    return out


def _config_from_json_safe(data):
    """Parse scenario_json back to config with date objects."""
    from copy import deepcopy
    config = deepcopy(data)
    sim = config.get("simulation", {})
    if sim.get("start_date") and isinstance(sim["start_date"], str):
        sim["start_date"] = date.fromisoformat(sim["start_date"])
    for stream in config.get("cashflow_streams", {}).get("income", []) + config.get("cashflow_streams", {}).get("expenses", []):
        for key in ("start_date", "end_date"):
            if stream.get(key) and isinstance(stream[key], str):
                stream[key] = date.fromisoformat(stream[key])
    return config

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Financial Simulation Results</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            padding: 40px;
        }
        h1 {
            color: #667eea;
            margin-bottom: 30px;
            font-size: 2em;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }
        h2 {
            color: #764ba2;
            margin-top: 30px;
            margin-bottom: 15px;
            font-size: 1.5em;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .card h3 {
            color: #667eea;
            font-size: 0.9em;
            text-transform: uppercase;
            margin-bottom: 10px;
            letter-spacing: 1px;
        }
        .card .value {
            font-size: 1.8em;
            font-weight: bold;
            color: #333;
        }
        .card .label {
            font-size: 0.85em;
            color: #666;
            margin-top: 5px;
        }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
            margin-top: 10px;
        }
        .status-success {
            background: #d4edda;
            color: #155724;
        }
        .status-warning {
            background: #fff3cd;
            color: #856404;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            font-size: 0.9em;
        }
        th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .positive {
            color: #28a745;
            font-weight: bold;
        }
        .negative {
            color: #dc3545;
            font-weight: bold;
        }
        .accounts-list, .debts-list {
            list-style: none;
            padding: 0;
        }
        .accounts-list li, .debts-list li {
            padding: 10px;
            margin: 5px 0;
            background: #f8f9fa;
            border-radius: 5px;
            display: flex;
            justify-content: space-between;
        }
        .paid-off {
            color: #28a745;
            font-weight: bold;
        }
        .whatif-panel {
            background: linear-gradient(135deg, #f0f4ff 0%, #e8eeff 100%);
            border: 2px solid #667eea;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 32px;
        }
        .whatif-panel h2 {
            margin-top: 0;
            font-size: 1.1em;
            color: #667eea;
        }
        .whatif-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            align-items: end;
            margin-bottom: 16px;
        }
        .whatif-grid label {
            display: block;
            font-size: 0.85em;
            color: #555;
            margin-bottom: 6px;
        }
        .whatif-grid input[type="number"] {
            width: 100%;
            max-width: 120px;
            padding: 8px 10px;
            border: 1px solid #667eea;
            border-radius: 6px;
        }
        .whatif-slider-wrap {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .whatif-slider-wrap input[type="range"] {
            flex: 1;
            min-width: 120px;
            max-width: 220px;
        }
        .whatif-slider-wrap .slider-val {
            font-weight: 600;
            min-width: 60px;
            color: #667eea;
        }
        .whatif-panel button {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 8px;
        }
        .whatif-panel button:hover {
            background: #5568d3;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>💰 Financial Simulation Results</h1>

        {% if show_whatif %}
        <div class="whatif-panel">
            <h2>🔮 What-if: tweak and re-run</h2>
            <form method="post" action="/run" id="whatif-form">
                <input type="hidden" name="scenario_json" value="{{ scenario_json }}">
                <div class="whatif-grid">
                    <div>
                        <label>Rent ± $<span id="rent-delta-val">{{ rent_delta }}</span></label>
                        <div class="whatif-slider-wrap">
                            <input type="range" name="rent_delta" id="rent_delta" min="-500" max="500" step="50" value="{{ rent_delta }}" oninput="document.getElementById('rent-delta-val').textContent=this.value">
                            <span class="slider-val" id="rent-delta-sign">{% if rent_delta > 0 %}+{% endif %}{{ rent_delta }}</span>
                        </div>
                    </div>
                    <div>
                        <label>Extra debt payment ($/mo)</label>
                        <input type="number" name="extra_debt_payment" min="0" step="10" value="{{ whatif_extra_payment }}">
                    </div>
                    <div>
                        <label>Investing: $/mo (fixed)</label>
                        <input type="number" name="monthly_investing" min="0" step="50" value="{{ whatif_monthly_investing }}">
                    </div>
                    <div>
                        <label>Investing: % of income</label>
                        <input type="number" name="monthly_investing_pct" min="0" max="100" step="1" value="{{ whatif_monthly_investing_pct }}">
                    </div>
                </div>
                <button type="submit">Re-run simulation</button>
            </form>
        </div>
        <script>
            (function(){
                var r = document.getElementById('rent_delta');
                if (r) {
                    function update() {
                        var v = r.value;
                        var sign = document.getElementById('rent-delta-sign');
                        if (sign) sign.textContent = (v > 0 ? '+' : '') + v;
                        var label = document.getElementById('rent-delta-val');
                        if (label) label.textContent = v;
                    }
                    r.addEventListener('input', update);
                    update();
                }
            })();
        </script>
        {% endif %}
        
        <div class="summary-grid">
            <div class="card">
                <h3>Start Date</h3>
                <div class="value">{{ start_date }}</div>
            </div>
            <div class="card">
                <h3>Months Simulated</h3>
                <div class="value">{{ months_simulated }}</div>
            </div>
            <div class="card">
                <h3>Mode</h3>
                <div class="value" style="font-size: 1.2em;">{{ mode_description }}</div>
            </div>
            {% if goal_net_worth %}
            <div class="card">
                <h3>Goal Net Worth</h3>
                <div class="value">${{ "{:,.2f}".format(goal_net_worth) }}</div>
            </div>
            {% endif %}
        </div>

        <h2>📊 Financial Position</h2>
        <div class="summary-grid">
            <div class="card">
                <h3>Starting Net Worth</h3>
                <div class="value {% if start_net_worth < 0 %}negative{% else %}positive{% endif %}">
                    ${{ "{:,.2f}".format(start_net_worth) }}
                </div>
                <div class="label">Accounts: ${{ "{:,.2f}".format(start_accounts_total) }}</div>
                <div class="label">Debts: ${{ "{:,.2f}".format(start_debts_total) }}</div>
            </div>
            <div class="card">
                <h3>Final Net Worth</h3>
                <div class="value {% if last_net_worth < 0 %}negative{% else %}positive{% endif %}">
                    ${{ "{:,.2f}".format(last_net_worth) }}
                </div>
                <div class="label">Accounts: ${{ "{:,.2f}".format(last_total_accounts) }}</div>
                <div class="label">Debts: ${{ "{:,.2f}".format(last_total_debts) }}</div>
            </div>
            <div class="card">
                <h3>Net Worth Change</h3>
                <div class="value {% if net_worth_change < 0 %}negative{% else %}positive{% endif %}">
                    ${{ "{:,.2f}".format(net_worth_change) }}
                </div>
            </div>
        </div>

        <h2>💵 Cashflows</h2>
        <div class="summary-grid">
            <div class="card">
                <h3>Total Income</h3>
                <div class="value positive">${{ "{:,.2f}".format(total_income) }}</div>
            </div>
            <div class="card">
                <h3>Total Expenses</h3>
                <div class="value negative">${{ "{:,.2f}".format(total_expenses) }}</div>
            </div>
            <div class="card">
                <h3>Total Debt Payments</h3>
                <div class="value">${{ "{:,.2f}".format(total_paid) }}</div>
            </div>
            <div class="card">
                <h3>Savings Rate</h3>
                <div class="value positive">{{ "{:.1%}".format(avg_savings_rate) }}</div>
            </div>
        </div>

        {% if debt_paid_off_month %}
        <div class="status-badge status-success">
            ✓ Debt paid off in {{ debt_paid_off_month }}
        </div>
        {% else %}
        <div class="status-badge status-warning">
            ⚠ Debt not paid off within simulation period
        </div>
        {% endif %}

        {% if goal_net_worth %}
            {% if goal_reached %}
            <div class="status-badge status-success">
                ✓ Goal reached in {{ goal_reached_month }}
            </div>
            {% else %}
            <div class="status-badge status-warning">
                ✗ Goal not reached: ${{ "{:,.2f}".format(last_net_worth) }} / ${{ "{:,.2f}".format(goal_net_worth) }}
            </div>
            {% endif %}
        {% endif %}

        <h2>🏦 Account Balances (Final)</h2>
        <ul class="accounts-list">
            {% for name, balance in accounts.items() %}
            <li>
                <span>{{ name }}{% if account_types and account_types.get(name) == 'invest' %} <em>(Investment)</em>{% else %} <em>(Savings)</em>{% endif %}</span>
                <span class="positive">${{ "{:,.2f}".format(balance) }}</span>
            </li>
            {% endfor %}
        </ul>

        <h2>💳 Debt Balances (Final)</h2>
        <ul class="debts-list">
            {% for name, balance in debts.items() %}
            <li>
                <span>{{ name }}</span>
                {% if balance <= 0 %}
                <span class="paid-off">PAID OFF</span>
                {% else %}
                <span class="negative">${{ "{:,.2f}".format(balance) }}</span>
                {% endif %}
            </li>
            {% endfor %}
        </ul>

        {% if show_table %}
        <h2>📅 Monthly Detail</h2>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Net Worth</th>
                    <th>Accounts</th>
                    <th>Debts</th>
                    <th>Income</th>
                    <th>Expenses</th>
                    <th>Payments</th>
                    <th>Surplus</th>
                </tr>
            </thead>
            <tbody>
                {% for record in records %}
                <tr>
                    <td>{{ record.date.strftime('%Y-%m') }}</td>
                    <td class="{% if record.net_worth < 0 %}negative{% else %}positive{% endif %}">
                        ${{ "{:,.2f}".format(record.net_worth) }}
                    </td>
                    <td>${{ "{:,.2f}".format(record.total_accounts) }}</td>
                    <td>${{ "{:,.2f}".format(record.total_debts) }}</td>
                    <td class="positive">${{ "{:,.2f}".format(record.income) }}</td>
                    <td class="negative">${{ "{:,.2f}".format(record.expenses) }}</td>
                    <td>${{ "{:,.2f}".format(record.total_payments) }}</td>
                    <td class="{% if record.monthly_surplus < 0 %}negative{% else %}positive{% endif %}">
                        ${{ "{:,.2f}".format(record.monthly_surplus) }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}
    </div>
</body>
</html>
"""

FORM_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Build Your Scenario – Financial Simulation</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            color: #333;
        }
        .container { max-width: 900px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); padding: 40px; }
        h1 { color: #667eea; margin-bottom: 10px; font-size: 1.8em; }
        p.subtitle { color: #666; margin-bottom: 28px; font-size: 0.95em; }
        h2 { color: #764ba2; margin-top: 28px; margin-bottom: 12px; font-size: 1.2em; border-bottom: 1px solid #eee; padding-bottom: 6px; }
        .form-grid { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 10px 14px; align-items: end; margin-bottom: 10px; }
        .form-grid.head { font-weight: 600; color: #555; font-size: 0.85em; }
        .form-grid.three { grid-template-columns: 1fr 1fr auto; }
        .form-grid.two { grid-template-columns: 1fr 1fr; }
        .form-grid.four { grid-template-columns: 1fr 1fr 1fr auto; }
        .form-hint { font-size: 0.9em; color: #666; margin-bottom: 10px; }
        input, select { padding: 8px 10px; border: 1px solid #ccc; border-radius: 6px; font-size: 0.95em; }
        input:focus, select:focus { outline: none; border-color: #667eea; }
        label { display: block; font-size: 0.85em; color: #666; margin-bottom: 4px; }
        .run-section { background: #f0f4ff; border-radius: 8px; padding: 20px; margin-top: 24px; border: 2px solid #667eea; }
        .run-section h2 { margin-top: 0; border: none; }
        .run-options { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-top: 12px; }
        .run-options label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
        .run-options input[type="radio"] { width: 18px; height: 18px; }
        .run-options .fixed-months { width: 80px; margin-left: 4px; }
        button { background: #667eea; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1em; font-weight: 600; cursor: pointer; margin-top: 20px; }
        button:hover { background: #5568d3; }
        .add-row { background: #e9ecef; color: #333; padding: 6px 14px; font-size: 0.9em; margin-top: 4px; }
        .add-row:hover { background: #dee2e6; }
        .error { background: #f8d7da; color: #721c24; padding: 12px; border-radius: 8px; margin-bottom: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Build your scenario</h1>
        <p class="subtitle">Enter your accounts, debts, income, and expenses. Then choose how to run the simulation.</p>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="post" action="/run">
            <h2>Simulation settings</h2>
            <div class="form-grid two">
                <div>
                    <label>Start date</label>
                    <input type="date" name="start_date" value="{{ start_date }}" required>
                </div>
                <div>
                    <label>Goal net worth ($) – optional, for "Run until goal"</label>
                    <input type="number" name="goal_net_worth" step="0.01" min="0" placeholder="e.g. 100000" value="{{ goal_net_worth }}">
                </div>
                <div>
                    <label>Cash account (where income lands)</label>
                    <select name="cash_account">
                        {% for name in cash_account_options %}
                        <option value="{{ name }}" {% if cash_account == name %}selected{% endif %}>{{ name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label>Extra monthly debt payment ($)</label>
                    <input type="number" name="payment_guess" step="0.01" min="0" value="{{ payment_guess }}">
                </div>
                <div>
                    <label>Investing: fixed $/mo (optional)</label>
                    <input type="number" name="monthly_investing" step="50" min="0" value="{{ monthly_investing }}" placeholder="0">
                </div>
                <div>
                    <label>Investing: % of monthly income (optional)</label>
                    <input type="number" name="monthly_investing_pct" step="1" min="0" max="100" value="{{ monthly_investing_pct }}" placeholder="0">
                </div>
            </div>

            <h2>Accounts</h2>
            <p class="form-hint">Use <strong>Savings</strong> for cash (HYSA, checking); use <strong>Investment</strong> for brokerage/retirement. Income lands in the cash account you select below.</p>
            <div class="form-grid head four"><span>Name</span><span>Balance ($)</span><span>APY (e.g. 0.042)</span><span>Type</span></div>
            {% for row in account_rows %}
            <div class="form-grid four">
                <input type="text" name="account_name" value="{{ row.name }}" placeholder="e.g. HYSA">
                <input type="number" name="account_balance" step="0.01" value="{{ row.balance }}" placeholder="0">
                <input type="number" name="account_rate" step="0.001" value="{{ row.rate }}" placeholder="0.04">
                <select name="account_type">
                    <option value="cash" {% if row.type == 'cash' %}selected{% endif %}>Savings</option>
                    <option value="invest" {% if row.type == 'invest' %}selected{% endif %}>Investment</option>
                </select>
            </div>
            {% endfor %}
            <button type="button" class="add-row" onclick="addRow('account')">+ Add account</button>

            <h2>Debts</h2>
            <div class="form-grid head"><span>Name</span><span>Balance ($)</span><span>APR (e.g. 0.22)</span><span>Min payment ($)</span></div>
            {% for row in debt_rows %}
            <div class="form-grid">
                <input type="text" name="debt_name" value="{{ row.name }}" placeholder="e.g. Credit Card">
                <input type="number" name="debt_balance" step="0.01" value="{{ row.balance }}" placeholder="0">
                <input type="number" name="debt_apr" step="0.01" value="{{ row.apr }}" placeholder="0.22">
                <input type="number" name="debt_min_payment" step="0.01" value="{{ row.min_payment }}" placeholder="35">
            </div>
            {% endfor %}
            <button type="button" class="add-row" onclick="addRow('debt')">+ Add debt</button>

            <h2>Income</h2>
            <div class="form-grid head three"><span>Name</span><span>Amount ($)</span><span>Cadence</span></div>
            {% for row in income_rows %}
            <div class="form-grid three">
                <input type="text" name="income_name" value="{{ row.name }}" placeholder="e.g. Salary">
                <input type="number" name="income_amount" step="0.01" value="{{ row.amount }}" placeholder="0">
                <select name="income_cadence"><option value="monthly" {% if row.cadence == 'monthly' %}selected{% endif %}>Monthly</option><option value="biweekly" {% if row.cadence == 'biweekly' %}selected{% endif %}>Biweekly</option></select>
            </div>
            {% endfor %}
            <button type="button" class="add-row" onclick="addRow('income')">+ Add income</button>

            <h2>Expenses</h2>
            <div class="form-grid head three"><span>Name</span><span>Amount ($)</span><span>Cadence</span></div>
            {% for row in expense_rows %}
            <div class="form-grid three">
                <input type="text" name="expense_name" value="{{ row.name }}" placeholder="e.g. Rent">
                <input type="number" name="expense_amount" step="0.01" value="{{ row.amount }}" placeholder="0">
                <select name="expense_cadence"><option value="monthly" {% if row.cadence == 'monthly' %}selected{% endif %}>Monthly</option><option value="biweekly" {% if row.cadence == 'biweekly' %}selected{% endif %}>Biweekly</option></select>
            </div>
            {% endfor %}
            <button type="button" class="add-row" onclick="addRow('expense')">+ Add expense</button>

            <div class="run-section">
                <h2>Run simulation</h2>
                <div class="run-options">
                    <label><input type="radio" name="run_mode" value="until_debt_paid" {{ 'checked' if run_mode == 'until_debt_paid' else '' }}> Run until debt paid off</label>
                    <label><input type="radio" name="run_mode" value="until_goal" {{ 'checked' if run_mode == 'until_goal' else '' }}> Run until goal net worth</label>
                    <label><input type="radio" name="run_mode" value="fixed" {{ 'checked' if run_mode == 'fixed' else '' }}> Run for <input type="number" name="fixed_months" class="fixed-months" min="1" value="{{ fixed_months }}" placeholder="60"> months</label>
                </div>
                <label style="margin-top:12px;"><input type="checkbox" name="show_table" value="1" {{ 'checked' if show_table else '' }}> Show monthly detail table in results</label>
                <button type="submit">Run simulation</button>
            </div>
        </form>
    </div>
    <script>
        function addRow(kind) {
            var form = document.querySelector('form');
            var sections = { account: [['account_name',''], ['account_balance', 0], ['account_rate', 0.04], ['account_type','cash']],
                debt: [['debt_name','Debt'], ['debt_balance', 0], ['debt_apr', 0.22], ['debt_min_payment', 35]],
                income: [['income_name','Income'], ['income_amount', 0], ['income_cadence','monthly']],
                expense: [['expense_name','Expense'], ['expense_amount', 0], ['expense_cadence','monthly']] };
            var spec = sections[kind];
            var firstRow = form.querySelector('[name="' + spec[0][0] + '"]');
            if (!firstRow) return;
            var div = firstRow.closest('.form-grid');
            var newDiv = div.cloneNode(true);
            newDiv.querySelectorAll('input, select').forEach(function(el, i) {
                el.value = spec[i] ? spec[i][1] : ''; el.name = el.name;
            });
            div.after(newDiv);
        }
    </script>
</body>
</html>
"""


def _summary_from_records(records, sim_cfg, stop_mode, mode_description):
    """Build simulation_data dict from records and config (for results template)."""
    if not records:
        return None
    first = records[0]
    last = records[-1]
    total_paid = sum(sum(r["payments"].values()) for r in records)
    total_income = sum(r["income"] for r in records)
    total_expenses = sum(r["expenses"] for r in records)
    start_accounts_total = sum(first["accounts_start"].values())
    start_debts_total = sum(first["debts_start"].values())
    start_net_worth = start_accounts_total - start_debts_total
    net_worth_change = last["net_worth"] - start_net_worth
    debt_paid_off_month = None
    for r in records:
        if r["total_debts"] <= 0:
            debt_paid_off_month = r["date"]
            break
    savings_rates = []
    for r in records:
        if r["income"] > 0:
            savings_rates.append((r["income"] - r["expenses"]) / r["income"])
    avg_savings_rate = sum(savings_rates) / len(savings_rates) if savings_rates else 0.0
    goal_net_worth = sim_cfg.get("goal_net_worth")
    goal_reached = bool(goal_net_worth and last["net_worth"] >= goal_net_worth)
    for r in records:
        r["total_payments"] = sum(r["payments"].values())
    return {
        "records": records,
        "start_date": first["date"],
        "months_simulated": len(records),
        "mode_description": mode_description,
        "goal_net_worth": goal_net_worth,
        "start_net_worth": start_net_worth,
        "start_accounts_total": start_accounts_total,
        "start_debts_total": start_debts_total,
        "net_worth_change": net_worth_change,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "total_paid": total_paid,
        "avg_savings_rate": avg_savings_rate,
        "debt_paid_off_month": debt_paid_off_month.strftime("%Y-%m") if debt_paid_off_month else None,
        "goal_reached": goal_reached,
        "show_table": False,
    }


def create_app(simulation_data):
    """Create Flask app with simulation data."""
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        # Prepare data for template
        records = simulation_data['records']
        first = records[0]
        last = records[-1]
        
        # Calculate total payments for each record
        for r in records:
            r['total_payments'] = sum(r['payments'].values())
        
        template_data = {
            'start_date': simulation_data['start_date'].strftime('%Y-%m-%d'),
            'months_simulated': len(records),
            'mode_description': simulation_data['mode_description'],
            'goal_net_worth': simulation_data.get('goal_net_worth'),
            'start_net_worth': simulation_data['start_net_worth'],
            'start_accounts_total': simulation_data['start_accounts_total'],
            'start_debts_total': simulation_data['start_debts_total'],
            'last_net_worth': last['net_worth'],
            'last_total_accounts': last['total_accounts'],
            'last_total_debts': last['total_debts'],
            'net_worth_change': simulation_data['net_worth_change'],
            'total_income': simulation_data['total_income'],
            'total_expenses': simulation_data['total_expenses'],
            'total_paid': simulation_data['total_paid'],
            'avg_savings_rate': simulation_data['avg_savings_rate'],
            'debt_paid_off_month': simulation_data.get('debt_paid_off_month'),
            'goal_reached': simulation_data.get('goal_reached', False),
            'goal_reached_month': last['date'].strftime('%Y-%m') if simulation_data.get('goal_reached') else None,
            'accounts': last['accounts'],
            'debts': last['debts'],
            'records': records,
            'show_table': simulation_data.get('show_table', False),
        }
        
        return render_template_string(HTML_TEMPLATE, **template_data)
    
    return app


def _default_form_data():
    """Default rows for the scenario form."""
    today = date.today().isoformat()
    account_rows = [{"name": "HYSA", "balance": "3000", "rate": "0.042", "type": "cash"}]
    return {
        "start_date": today,
        "goal_net_worth": "100000",
        "cash_account": "HYSA",
        "payment_guess": "320",
        "monthly_investing": "0",
        "monthly_investing_pct": "0",
        "cash_account_options": [r["name"] for r in account_rows if r.get("type", "cash") == "cash"],
        "account_rows": account_rows,
        "debt_rows": [{"name": "Credit Card", "balance": "5815", "apr": "0.2249", "min_payment": "35"}],
        "income_rows": [{"name": "Salary", "amount": "5586", "cadence": "monthly"}],
        "expense_rows": [
            {"name": "Rent", "amount": "850", "cadence": "monthly"},
            {"name": "Utilities", "amount": "75", "cadence": "monthly"},
            {"name": "Food/Fun", "amount": "800", "cadence": "monthly"},
        ],
        "run_mode": "until_debt_paid",
        "fixed_months": "60",
        "show_table": False,
        "error": None,
    }


def create_interactive_app():
    """Flask app with scenario form and /run that builds scenario and shows results."""
    app = Flask(__name__)

    @app.route("/")
    def index():
        data = _default_form_data()
        return render_template_string(FORM_HTML_TEMPLATE, **data)

    @app.route("/run", methods=["POST"])
    def run_simulation():
        # What-if re-run: apply overrides to saved scenario and simulate
        scenario_json_str = request.form.get("scenario_json")
        if scenario_json_str:
            try:
                data = json.loads(scenario_json_str)
                config = _config_from_json_safe(data)
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                data = _default_form_data()
                return render_template_string(FORM_HTML_TEMPLATE, error=f"Invalid saved scenario: {e}", **data)
            rent_delta = float(request.form.get("rent_delta") or 0)
            for e in config.get("cashflow_streams", {}).get("expenses", []):
                if (e.get("name") or "").strip() == "Rent":
                    e["amount"] = float(e.get("amount", 0)) + rent_delta
                    break
            config["payment_guess"] = float(request.form.get("extra_debt_payment") or 0)
            inv = float(request.form.get("monthly_investing") or 0)
            inv_pct = float(request.form.get("monthly_investing_pct") or 0)
            config["simulation"]["monthly_investing"] = inv
            config["simulation"]["monthly_investing_pct"] = inv_pct
            if inv > 0 or inv_pct > 0:
                accounts = config.get("instruments", {}).get("accounts", [])
                invest_accounts = [a for a in accounts if (a.get("type") or "cash") == "invest"]
                if invest_accounts:
                    config["simulation"]["investing_account"] = invest_accounts[0]["name"]
                else:
                    config["simulation"]["investing_account"] = "Investments"
                    if not any((a.get("name") or "") == "Investments" for a in accounts):
                        accounts.append({"name": "Investments", "balance": 0.0, "rate_schedule": 0.0, "type": "invest"})
            else:
                config["simulation"]["investing_account"] = None
            sim_cfg = config.get("simulation", {})
            start_d = sim_cfg.get("start_date", date.today())
            months_max = sim_cfg.get("months", 120)
            run_mode = data.get("run_mode", "until_debt_paid")
            show_table = data.get("show_table", False)
            if run_mode == "until_goal":
                stop_mode = "goal"
                mode_description = f"Run until net worth goal (${sim_cfg.get('goal_net_worth', 0):,.2f})" if sim_cfg.get("goal_net_worth") else "Run until net worth goal"
            elif run_mode == "fixed":
                stop_mode = "fixed"
                mode_description = f"Fixed {months_max}-month simulation"
            else:
                stop_mode = "debt"
                mode_description = "Run until debt paid off"
            records = simulate(config, start_d, months_max, stop_mode=stop_mode)
            if not records:
                data = _default_form_data()
                return render_template_string(FORM_HTML_TEMPLATE, error="No simulation steps.", **data)
            summary = _summary_from_records(records, sim_cfg, stop_mode, mode_description)
            summary["show_table"] = show_table
            last = records[-1]
            summary["goal_reached_month"] = last["date"].strftime("%Y-%m") if summary.get("goal_reached") else None
            updated_json = _config_to_json_safe(config)
            updated_json["run_mode"] = run_mode
            updated_json["show_table"] = show_table
            for r in records:
                r["total_payments"] = sum(r["payments"].values())
            template_data = {
                "start_date": summary["start_date"].strftime("%Y-%m-%d"),
                "months_simulated": summary["months_simulated"],
                "mode_description": summary["mode_description"],
                "goal_net_worth": summary.get("goal_net_worth"),
                "start_net_worth": summary["start_net_worth"],
                "start_accounts_total": summary["start_accounts_total"],
                "start_debts_total": summary["start_debts_total"],
                "last_net_worth": last["net_worth"],
                "last_total_accounts": last["total_accounts"],
                "last_total_debts": last["total_debts"],
                "net_worth_change": summary["net_worth_change"],
                "total_income": summary["total_income"],
                "total_expenses": summary["total_expenses"],
                "total_paid": summary["total_paid"],
                "avg_savings_rate": summary["avg_savings_rate"],
                "debt_paid_off_month": summary.get("debt_paid_off_month"),
                "goal_reached": summary.get("goal_reached", False),
                "goal_reached_month": summary.get("goal_reached_month"),
                "accounts": last["accounts"],
                "debts": last["debts"],
                "account_types": {a["name"]: a.get("type", "cash") for a in config.get("instruments", {}).get("accounts", [])},
                "records": records,
                "show_table": show_table,
                "show_whatif": True,
                "scenario_json": json.dumps(updated_json),
                "rent_delta": int(rent_delta),
                "whatif_extra_payment": int(config["payment_guess"]) if config["payment_guess"] == int(config["payment_guess"]) else config["payment_guess"],
                "whatif_monthly_investing": int(inv) if inv == int(inv) else inv,
                "whatif_monthly_investing_pct": int(inv_pct) if inv_pct == int(inv_pct) else inv_pct,
            }
            return render_template_string(HTML_TEMPLATE, **template_data)

        names = request.form.getlist("account_name")
        balances = request.form.getlist("account_balance")
        rates = request.form.getlist("account_rate")
        types = request.form.getlist("account_type")
        accounts = []
        for n, b, r, t in zip(names, balances, rates, types or ([],) * len(names)):
            if (n or "").strip():
                acc_type = (t or "cash").strip().lower() if t else "cash"
                if acc_type not in ("cash", "invest"):
                    acc_type = "cash"
                accounts.append({"name": n.strip(), "balance": b or 0, "rate_schedule": r or 0, "type": acc_type})

        dnames = request.form.getlist("debt_name")
        dbalances = request.form.getlist("debt_balance")
        daprs = request.form.getlist("debt_apr")
        dmins = request.form.getlist("debt_min_payment")
        debts = []
        for n, b, apr, m in zip(dnames, dbalances, daprs, dmins):
            if (n or "").strip():
                debts.append({
                    "name": n.strip(),
                    "balance": b or 0,
                    "apr_schedule": apr or 0,
                    "min_payment_rule": {"type": "fixed", "amount": m or 0},
                })

        inames = request.form.getlist("income_name")
        iamounts = request.form.getlist("income_amount")
        icadences = request.form.getlist("income_cadence")
        income = []
        for n, a, c in zip(inames, iamounts, icadences):
            if (n or "").strip():
                income.append({"name": n.strip(), "amount": a or 0, "cadence": c or "monthly"})

        enames = request.form.getlist("expense_name")
        eamounts = request.form.getlist("expense_amount")
        ecadences = request.form.getlist("expense_cadence")
        expenses = []
        for n, a, c in zip(enames, eamounts, ecadences):
            if (n or "").strip():
                expenses.append({"name": n.strip(), "amount": a or 0, "cadence": c or "monthly"})

        start_date = request.form.get("start_date") or date.today().isoformat()
        goal_net_worth = request.form.get("goal_net_worth") or None
        # Cash account for income: default to first savings (cash) account
        cash_accounts = [a["name"] for a in accounts if a.get("type", "cash") == "cash"]
        cash_account = request.form.get("cash_account") or (cash_accounts[0] if cash_accounts else (accounts[0]["name"] if accounts else "HYSA"))
        payment_guess = request.form.get("payment_guess") or 0
        monthly_investing = request.form.get("monthly_investing") or 0
        monthly_investing_pct = request.form.get("monthly_investing_pct") or 0
        run_mode = request.form.get("run_mode") or "until_debt_paid"
        fixed_months = request.form.get("fixed_months") or "60"
        show_table = request.form.get("show_table") == "1"

        if not accounts:
            data = _default_form_data()
            return render_template_string(FORM_HTML_TEMPLATE, error="Add at least one account.", **data)

        try:
            config = build_scenario(
                accounts=accounts,
                debts=debts,
                income=income,
                expenses=expenses,
                start_date=start_date,
                months=int(fixed_months),
                cash_account=cash_account,
                goal_net_worth=goal_net_worth,
                payment_guess=float(payment_guess or 0),
                monthly_investing=float(monthly_investing or 0),
                monthly_investing_pct=float(monthly_investing_pct or 0),
            )
        except Exception as e:
            data = _default_form_data()
            data["cash_account_options"] = [a["name"] for a in accounts if a.get("type", "cash") == "cash"] or [a["name"] for a in accounts]
            return render_template_string(FORM_HTML_TEMPLATE, error=f"Invalid scenario: {e}", **data)

        sim_cfg = config.get("simulation", {})
        start_d = sim_cfg.get("start_date", date.today())
        months_max = sim_cfg.get("months", 120)
        if run_mode == "until_goal":
            stop_mode = "goal"
            mode_description = f"Run until net worth goal (${sim_cfg.get('goal_net_worth', 0):,.2f})" if sim_cfg.get("goal_net_worth") else "Run until net worth goal"
        elif run_mode == "fixed":
            stop_mode = "fixed"
            mode_description = f"Fixed {months_max}-month simulation"
        else:
            stop_mode = "debt"
            mode_description = "Run until debt paid off"

        records = simulate(config, start_d, months_max, stop_mode=stop_mode)
        if not records:
            data = _default_form_data()
            data["cash_account_options"] = [a["name"] for a in accounts if a.get("type", "cash") == "cash"] or [a["name"] for a in accounts]
            return render_template_string(FORM_HTML_TEMPLATE, error="No simulation steps (e.g. no debts or invalid setup).", **data)

        summary = _summary_from_records(records, sim_cfg, stop_mode, mode_description)
        summary["show_table"] = show_table
        last = records[-1]
        summary["goal_reached_month"] = last["date"].strftime("%Y-%m") if summary.get("goal_reached") else None
        template_data = {
            "start_date": summary["start_date"].strftime("%Y-%m-%d"),
            "months_simulated": summary["months_simulated"],
            "mode_description": summary["mode_description"],
            "goal_net_worth": summary.get("goal_net_worth"),
            "start_net_worth": summary["start_net_worth"],
            "start_accounts_total": summary["start_accounts_total"],
            "start_debts_total": summary["start_debts_total"],
            "last_net_worth": last["net_worth"],
            "last_total_accounts": last["total_accounts"],
            "last_total_debts": last["total_debts"],
            "net_worth_change": summary["net_worth_change"],
            "total_income": summary["total_income"],
            "total_expenses": summary["total_expenses"],
            "total_paid": summary["total_paid"],
            "avg_savings_rate": summary["avg_savings_rate"],
            "debt_paid_off_month": summary.get("debt_paid_off_month"),
            "goal_reached": summary.get("goal_reached", False),
            "goal_reached_month": summary.get("goal_reached_month"),
            "accounts": last["accounts"],
            "debts": last["debts"],
            "account_types": {a["name"]: a.get("type", "cash") for a in config.get("instruments", {}).get("accounts", [])},
            "records": records,
            "show_table": show_table,
        }
        for r in records:
            r["total_payments"] = sum(r["payments"].values())
        # Pass scenario_json and what-if defaults so results page can re-run with tweaks
        scenario_json_dict = _config_to_json_safe(config)
        scenario_json_dict["run_mode"] = run_mode
        scenario_json_dict["show_table"] = show_table
        inv_used = config.get("simulation", {}).get("monthly_investing") or 0
        inv_pct_used = config.get("simulation", {}).get("monthly_investing_pct") or 0
        template_data["show_whatif"] = True
        template_data["scenario_json"] = json.dumps(scenario_json_dict)
        template_data["rent_delta"] = 0
        template_data["whatif_extra_payment"] = int(config["payment_guess"]) if config["payment_guess"] == int(config["payment_guess"]) else config["payment_guess"]
        template_data["whatif_monthly_investing"] = int(inv_used) if inv_used == int(inv_used) else inv_used
        template_data["whatif_monthly_investing_pct"] = int(inv_pct_used) if inv_pct_used == int(inv_pct_used) else inv_pct_used
        return render_template_string(HTML_TEMPLATE, **template_data)

    return app


def serve_results(simulation_data, port=3000, open_browser=True):
    """Serve simulation results on localhost."""
    app = create_app(simulation_data)
    
    if open_browser:
        def open_browser_delayed():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open(f'http://localhost:{port}')
        
        threading.Thread(target=open_browser_delayed, daemon=True).start()
    
    print(f"\n🌐 Starting web server on http://localhost:{port}")
    print("   Press Ctrl+C to stop the server\n")
    
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


def serve_interactive_app(port=3000, open_browser=True):
    """Serve the scenario builder and run simulation from the browser."""
    app = create_interactive_app()
    if open_browser:
        def open_browser_delayed():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=open_browser_delayed, daemon=True).start()
    print(f"\n🌐 Scenario builder at http://localhost:{port}")
    print("   Enter accounts, debts, income, expenses → choose run mode → Run simulation")
    print("   Press Ctrl+C to stop the server\n")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
