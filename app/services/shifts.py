"""Pure business logic for teller shifts — no DB access, no I/O."""


def compute_expected_cash(
    opening_cash: float,
    total_sold: float,
    total_bought: float,
    total_commission: float = 0.0,
    total_replenishment: float = 0.0,
    total_petty_cash: float = 0.0,
) -> float:
    """
    What the cashier's drawer should hold at shift close.

    BUY  → Kedco pays PHP out → drawer shrinks
    SELL → Kedco receives PHP → drawer grows
    Commission paid out → drawer shrinks
    Replenishment in    → drawer grows
    Petty cash paid out (expenses) → drawer shrinks
    """
    return round(
        opening_cash + total_sold - total_bought - total_commission
        + total_replenishment - total_petty_cash,
        2,
    )


def compute_variance(closing_cash: float, expected_cash: float) -> float:
    return round(closing_cash - expected_cash, 2)


def compute_expected_cash_treasurer(
    opening_cash: float,
    from_dispatches: float = 0.0,
    from_cashier: float = 0.0,
    bale_peso: float = 0.0,
    vault_returns: float = 0.0,
) -> float:
    """
    Opening + dispatches + cashier handoffs − bale peso + vault returns.

    BALE PESO is segregated as vault accountability (subtracts).
    VAULT RETURNS are drawer-to-vault deposits she made during shift —
    they cancel prior bale liability, so they add back to expected own-money.
    """
    return round(
        opening_cash + from_dispatches + from_cashier - bale_peso + vault_returns,
        2,
    )
