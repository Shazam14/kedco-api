# ─────────────────────────────────────────────
# Kedco FX — Core Business Logic (SERVER SIDE)
#
# This is the Python equivalent of data.ts logic.
# Keeping this server-side means:
#  - Clients never see raw rates or avg costs
#  - Business rules enforced in one place
#  - ERPNext can consume the same functions
# ─────────────────────────────────────────────

from dataclasses import dataclass
from typing import List


@dataclass
class CarryIn:
    qty: float
    rate: float

    @property
    def php_value(self) -> float:
        return self.qty * self.rate


@dataclass
class TodayBuy:
    qty: float
    rate: float

    @property
    def php_cost(self) -> float:
        return self.qty * self.rate


@dataclass
class PositionResult:
    total_qty: float
    daily_avg_cost: float       # per-day weighted avg — resets daily
    stock_value_php: float      # total_qty × today_sell_rate
    today_gain_per_unit: float  # today_sell_rate − daily_avg_cost
    unrealized_php: float       # today_gain_per_unit × total_qty


def compute_position(
    carry_in: CarryIn,
    today_buys: List[TodayBuy],
    today_sell_rate: float,
) -> PositionResult:
    """
    KEN'S AVERAGING RULE:
    - Averaging is PER DAY only.
    - Yesterday's unsold stock enters today at yesterday's closing sell rate.
    - Each buy today is blended WITH the carry-in.
    - daily_avg = (carry_qty × carry_rate + Σ(buy_qty × buy_rate))
                  ÷ (carry_qty + Σ buy_qty)
    - THAN per sell = (sell_rate − daily_avg) × units_sold
    - At EOD the avg RESETS. Previous days never contaminate today's gain.
    """
    total_buy_qty = sum(b.qty for b in today_buys)
    total_buy_cost = sum(b.php_cost for b in today_buys)

    total_qty = carry_in.qty + total_buy_qty
    total_cost = carry_in.php_value + total_buy_cost

    daily_avg_cost = total_cost / total_qty if total_qty > 0 else 0.0

    stock_value_php = total_qty * today_sell_rate
    today_gain_per_unit = today_sell_rate - daily_avg_cost
    unrealized_php = today_gain_per_unit * total_qty

    return PositionResult(
        total_qty=total_qty,
        daily_avg_cost=daily_avg_cost,
        stock_value_php=stock_value_php,
        today_gain_per_unit=today_gain_per_unit,
        unrealized_php=unrealized_php,
    )


def compute_than(sell_rate: float, daily_avg_cost: float, units_sold: float) -> float:
    """
    THAN = (sell_rate − daily_avg_cost) × units_sold
    This is the actual profit earned on a sell transaction.
    """
    return (sell_rate - daily_avg_cost) * units_sold
