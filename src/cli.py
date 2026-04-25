import asyncio

from mode_enum import Mode
from core import build_report

if __name__ == "__main__":
    print("📈 Financial Intelligence Terminal")

    user_input = input("Enter tickers (AAPL, TSLA, NVDA): ")

    symbols = [t.strip().upper() for t in user_input.replace(",", " ").split()]

    asyncio.run(build_report(Mode.CLI, symbols))
