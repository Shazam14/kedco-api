"""Pure business logic for teller shifts — no DB access, no I/O."""


def compute_expected_cash(
    opening_cash: float,
    total_sold: float,
    total_bought: float,
    total_commission: float = 0.0,
    total_replenishment: float = 0.0,
) -> float:
    """
    What the cashier's drawer should hold at shift close.

    BUY  → Kedco pays PHP out → drawer shrinks
    SELL → Kedco receives PHP → drawer grows
    Commission paid out → drawer shrinks
    Replenishment in    → drawer grows
    """
    return round(
        opening_cash + total_sold - total_bought - total_commission + total_replenishment,
        2,
    )


def compute_variance(closing_cash: float, expected_cash: float) -> float:
    return round(closing_cash - expected_cash, 2)
