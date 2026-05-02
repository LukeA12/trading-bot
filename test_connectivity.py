"""Quick connectivity check for Polymarket and Kalshi weather sources."""
import asyncio
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from backend.sources.polymarket_weather import load_poly_temp_contracts
from backend.sources.kalshi_weather import load_kalshi_temp_contracts
from backend.sources.kalshi_api import kalshi_configured


async def main():
    print("\n=== Polymarket weather contracts ===")
    poly = await load_poly_temp_contracts()
    if poly:
        for c in poly[:10]:
            print(f"  [{c.city_key}] {c.title}")
            print(f"       date={c.target_date}  threshold={c.threshold_f}°F  "
                  f"yes={c.yes_price:.2f}  vol={c.volume:.0f}")
    else:
        print("  (none found)")

    print("\n=== Kalshi weather contracts ===")
    if not kalshi_configured():
        print("  Kalshi not configured (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH missing)")
    else:
        kalshi = await load_kalshi_temp_contracts()
        if kalshi:
            for c in kalshi[:10]:
                print(f"  [{c.city_key}] {c.title}")
                print(f"       date={c.target_date}  threshold={c.threshold_f}°F  yes={c.yes_price:.2f}")
        else:
            print("  (none found)")


asyncio.run(main())
