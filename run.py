#!/usr/bin/env python3
"""
Main entry point for the debt/cash simulation.
Loads config, runs the simulator, and prints results.
"""
from datetime import date

from config import CONFIG
from engine import simulate


def main():
    start_date = date.today()
    max_months = 120  # cap at 10 years

    records = simulate(CONFIG, start_date, max_months)

    if not records:
        print("No simulation steps (debt already zero or invalid config).")
        return

    # Summary
    last = records[-1]
    total_paid = sum(r["payment"] for r in records)
    months_to_zero = len(records)

    print("=== Simulation summary ===")
    print(f"Start date:        {start_date}")
    print(f"Months simulated:  {months_to_zero}")
    print(f"Total paid:        ${total_paid:,.2f}")
    print(f"Final debt:        ${last['debt_end']:,.2f}")
    print(f"Final cash:        ${last['cash_end']:,.2f}")
    print()

    # Monthly table (first few and last few)
    print("=== Monthly detail (first 6 and last 6 months) ===")
    headers = ("Date", "Debt start", "Payment", "Debt end", "Cash end")
    col_widths = (12, 12, 10, 12, 12)
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("-" * 60)

    def row(r):
        return (
            r["date"].strftime("%Y-%m"),
            f"${r['debt_start']:,.2f}",
            f"${r['payment']:,.2f}",
            f"${r['debt_end']:,.2f}",
            f"${r['cash_end']:,.2f}",
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
    if last["debt_end"] <= 0:
        print("Debt paid off.")
    else:
        print(f"Debt not paid off after {max_months} months.")


if __name__ == "__main__":
    main()
