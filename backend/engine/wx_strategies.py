"""Weather trading strategy definitions.

Strategy 1: Baseline — enter on any signal passing threshold, hold to settlement.
Strategy 2: Same entry as S1 + early exit logic based on entry price and time-to-settle.
Strategy 3: Higher threshold (15%+), tiered position sizing, hold to settlement.
"""
from backend.env import cfg

# Strategy 1 & 2 use the global WEATHER_MIN_EDGE_THRESHOLD
STRATEGY_1_THRESHOLD = cfg.WEATHER_MIN_EDGE_THRESHOLD
STRATEGY_2_THRESHOLD = cfg.WEATHER_MIN_EDGE_THRESHOLD
STRATEGY_3_THRESHOLD = 0.15

# Strategy 3 tiered sizing (multiples of base unit)
STRATEGY_3_TIERS = [
    (0.35, 5),  # 35%+ edge → 5 units
    (0.25, 2),  # 25%+ edge → 2 units
    (0.15, 1),  # 15%+ edge → 1 unit
]

# Base unit size
BASE_UNIT = 75.0

# Strategy 2 early exit parameters
EARLY_EXIT_ENTRY_THRESHOLD = 0.45  # Exit early only if entry < 45¢
EARLY_EXIT_MIN_HOURS_REMAINING = 4  # Only exit if 4+ hours left
EARLY_EXIT_HOLD_AGREEMENT = 0.70   # Hold to settlement if agreement >= 70%
EARLY_EXIT_HOLD_ENTRY = 0.50       # Hold to settlement if entry >= 50¢
NO_EXIT_HOURS_REMAINING = 2        # Never exit within 2 hours of settlement


def compute_strategy_3_size(edge: float) -> float:
    """Compute position size for Strategy 3 based on edge tier."""
    abs_edge = abs(edge)
    for threshold, multiplier in STRATEGY_3_TIERS:
        if abs_edge >= threshold:
            return BASE_UNIT * multiplier
    return 0.0


def should_take_trade_s3(edge: float) -> bool:
    """Strategy 3 only takes trades at 15%+ edge."""
    return abs(edge) >= STRATEGY_3_THRESHOLD
