"""Export all trades from the database to a CSV file."""
import csv
import sys
from datetime import datetime
from backend.storage.models import DbSession, Position


COLUMNS = [
    "id",
    "timestamp",
    "market_ticker",
    "platform",
    "market_type",
    "event_slug",
    "direction",
    "entry_price",
    "size",
    "model_probability",
    "market_price_at_entry",
    "edge_at_entry",
    "settled",
    "settlement_time",
    "settlement_value",
    "result",
    "pnl",
]


def format_value(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return ""
    return value


def export_trades(output_path: str = "trades.csv"):
    db = DbSession()
    try:
        trades = db.query(Position).order_by(Position.timestamp).all()

        if not trades:
            print("No trades found in the database.")
            return

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            for trade in trades:
                writer.writerow([format_value(getattr(trade, col)) for col in COLUMNS])

        print(f"Exported {len(trades)} trade(s) to {output_path}")
    finally:
        db.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "trades.csv"
    export_trades(path)
