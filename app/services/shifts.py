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
) -> float:
    """
    Treasurer's drawer doesn't transact (or rarely does — those go through cashier formula
    when role=cashier). Her cash flows are returns from the field.

    Opening (treasurer's own float)
    + FROM DISPATCHES (rider remit_php returned during her shift)
    + FROM CASHIER    (cashier closing_cash handed back during her shift)

    BALE PESO is the vault loan she's holding — physically present in drawer but
    accounted as a liability separately (variance = actual − (expected + bale)).
    """
    return round(opening_cash + from_dispatches + from_cashier, 2)
