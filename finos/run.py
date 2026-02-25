#!/usr/bin/env python3
"""
Main entry point for the debt/cash simulation.
Loads config, runs the simulator, and prints results.
"""
import argparse
from config import CONFIG
from engine import simulate
from web_view import serve_results, serve_interactive_app


def main():
    parser = argparse.ArgumentParser(
        description="Run financial simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                    # Run until debt is paid off (default)
  python run.py --months 12        # Run for fixed 12 months
  python run.py --until-debt-paid  # Run until debt is paid off
  python run.py --until-goal       # Run until net worth goal is reached
  python run.py --until-goal --show-table  # Show monthly table
        """
    )
    parser.add_argument(
        "--months",
        type=int,
        metavar="N",
        help="Run simulation for fixed N months (fixed mode)"
    )
    parser.add_argument(
        "--until-debt-paid",
        action="store_true",
        help="Run simulation until debt is paid off (default behavior)"
    )
    parser.add_argument(
        "--until-goal",
        action="store_true",
        help="Run simulation until net worth goal is reached"
    )
    parser.add_argument(
        "--show-table",
        action="store_true",
        help="Show monthly detail table (hidden by default)"
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Display results in web browser (localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Port for web server (default: 3000)"
    )
    parser.add_argument(
        "--web-app",
        action="store_true",
        help="Start interactive web app: enter scenario in browser, then run until goal / debt paid / fixed"
    )
    
    args = parser.parse_args()
    
    if args.web_app:
        serve_interactive_app(port=args.port)
        return
    
    sim_cfg = CONFIG.get("simulation", {})
    start_date = sim_cfg.get("start_date")
    
    # Determine simulation mode
    if args.months:
        # Fixed duration mode
        months = args.months
        stop_mode = "fixed"
        mode_description = f"Fixed {months}-month simulation"
    elif args.until_goal:
        # Goal-based mode
        months = sim_cfg.get("months", 120)
        stop_mode = "goal"
        goal_net_worth = sim_cfg.get("goal_net_worth", None)
        if goal_net_worth:
            mode_description = f"Run until net worth goal (${goal_net_worth:,.2f})"
        else:
            mode_description = "Run until net worth goal (not configured)"
    else:
        # Default: debt-based mode
        months = sim_cfg.get("months", 120)
        stop_mode = "debt"
        mode_description = "Run until debt paid off"
    
    records = simulate(CONFIG, start_date, months, stop_mode=stop_mode)
    
    if not records:
        print("No simulation steps (all debts already zero or invalid config).")
        return
    
    # Summary
    last = records[-1]
    first = records[0]
    
    total_paid = sum(sum(r["payments"].values()) for r in records)
    total_income = sum(r["income"] for r in records)
    total_expenses = sum(r["expenses"] for r in records)
    months_simulated = len(records)
    
    # Calculate starting position from first record's start values
    start_accounts_total = sum(first["accounts_start"].values())
    start_debts_total = sum(first["debts_start"].values())
    start_net_worth = start_accounts_total - start_debts_total
    net_worth_change = last["net_worth"] - start_net_worth
    
    # Find month when debt is paid off
    debt_paid_off_month = None
    for r in records:
        if r["total_debts"] <= 0:
            debt_paid_off_month = r["date"]
            break
    
    # Calculate savings rate (average across all months)
    savings_rates = []
    for r in records:
        if r["income"] > 0:
            savings_rate = (r["income"] - r["expenses"]) / r["income"]
            savings_rates.append(savings_rate)
    avg_savings_rate = sum(savings_rates) / len(savings_rates) if savings_rates else 0.0
    
    # Check if goal was reached
    goal_reached = False
    goal_net_worth = sim_cfg.get("goal_net_worth", None)
    if goal_net_worth and last["net_worth"] >= goal_net_worth:
        goal_reached = True
    
    print("=== Simulation Summary ===")
    print(f"Start date:           {start_date}")
    print(f"Months simulated:     {months_simulated}")
    print(f"Mode:                 {mode_description}")
    if goal_net_worth:
        print(f"Goal net worth:       ${goal_net_worth:,.2f}")
    print()
    print("=== Financial Position ===")
    print(f"Starting net worth:   ${start_net_worth:,.2f}")
    print(f"  Accounts:           ${start_accounts_total:,.2f}")
    print(f"  Debts:              ${start_debts_total:,.2f}")
    print()
    print(f"Final net worth:      ${last['net_worth']:,.2f}")
    print(f"  Accounts:           ${last['total_accounts']:,.2f}")
    print(f"  Debts:              ${last['total_debts']:,.2f}")
    print(f"Net worth change:     ${net_worth_change:,.2f}")
    print()
    print("=== Cashflows ===")
    print(f"Total income:         ${total_income:,.2f}")
    print(f"Total expenses:       ${total_expenses:,.2f}")
    print(f"Total debt payments:  ${total_paid:,.2f}")
    print(f"Savings rate:         {avg_savings_rate:.1%}")
    if debt_paid_off_month:
        print(f"Debt paid off:        {debt_paid_off_month.strftime('%Y-%m')}")
    else:
        print(f"Debt paid off:        Not paid off within simulation period")
    if goal_net_worth:
        if goal_reached:
            print(f"Goal reached:         ✓ Yes ({last['date'].strftime('%Y-%m')})")
        else:
            print(f"Goal reached:         ✗ No (${last['net_worth']:,.2f} / ${goal_net_worth:,.2f})")
    print()
    
    # Account breakdown
    print("=== Account Balances (Final) ===")
    for name, balance in last["accounts"].items():
        print(f"  {name}: ${balance:,.2f}")
    print()
    
    # Debt breakdown
    print("=== Debt Balances (Final) ===")
    all_debts_paid = True
    for name, balance in last["debts"].items():
        status = "PAID OFF" if balance <= 0 else f"${balance:,.2f}"
        print(f"  {name}: {status}")
        if balance > 0:
            all_debts_paid = False
    print()
    
    # Monthly detail table (only shown if --show-table flag is used)
    if args.show_table:
        print("=== Monthly Detail (first 6 and last 6 months) ===")
        headers = ("Date", "Net Worth", "Accounts", "Debts", "Income", "Expenses", "Payments", "Surplus")
        col_widths = (12, 14, 12, 12, 10, 10, 10, 10)
        fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*headers))
        print("-" * 100)
        
        def row(r):
            total_payments = sum(r["payments"].values())
            return (
                r["date"].strftime("%Y-%m"),
                f"${r['net_worth']:,.2f}",
                f"${r['total_accounts']:,.2f}",
                f"${r['total_debts']:,.2f}",
                f"${r['income']:,.2f}",
                f"${r['expenses']:,.2f}",
                f"${total_payments:,.2f}",
                f"${r['monthly_surplus']:,.2f}",
            )
        
        show = records[:6]
        for r in show:
            print(fmt.format(*row(r)))
        if len(records) > 12:
            print("  ...")
            show = records[-6:]
        elif len(records) > 6:
            show = records[6:]
        for r in show:
            print(fmt.format(*row(r)))
        print()
    
    # Final status
    if stop_mode == "goal" and goal_reached:
        print("✓ Net worth goal reached!")
    elif stop_mode == "goal" and not goal_reached:
        print(f"⚠ Goal not reached after {months_simulated} months.")
    elif all_debts_paid:
        print("✓ All debts paid off!")
    else:
        print(f"⚠ Debts remain after {months_simulated} months.")
    
    # Serve web view if requested
    if args.web:
        simulation_data = {
            'records': records,
            'start_date': start_date,
            'months_simulated': months_simulated,
            'mode_description': mode_description,
            'goal_net_worth': goal_net_worth,
            'start_net_worth': start_net_worth,
            'start_accounts_total': start_accounts_total,
            'start_debts_total': start_debts_total,
            'net_worth_change': net_worth_change,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'total_paid': total_paid,
            'avg_savings_rate': avg_savings_rate,
            'debt_paid_off_month': debt_paid_off_month.strftime('%Y-%m') if debt_paid_off_month else None,
            'goal_reached': goal_reached,
            'show_table': args.show_table,
        }
        serve_results(simulation_data, port=args.port)


if __name__ == "__main__":
    main()
