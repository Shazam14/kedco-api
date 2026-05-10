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
    dispatches_out: float = 0.0,
    from_cashier: float = 0.0,
    bale_peso: float = 0.0,
    inter_branch_in: float = 0.0,
    inter_branch_out: float = 0.0,
    vault_returns: float = 0.0,
    expenses: float = 0.0,
    cheques_cleared: float = 0.0,
) -> float:
    """
    Expected physical cash in the treasurer's drawer at any moment.

    Drawer-side rolling formula:
      opening
        + (remits in − dispatched out)        rider cash flow
        + from_cashier                        cashier shift-close handoffs
        + bale_peso                           vault → drawer (treasurer pulled cash)
        + inter_branch_in                     other branch → this drawer
        − inter_branch_out                    this drawer → other branch
        − vault_returns                       signed net of vault movements
                                              (+ = drawer→vault deposit,
                                               − = vault→drawer withdrawal)
        + cheques_cleared                     cheques confirmed cleared today
        − expenses                            treasurer-bucket expenses (non-shift petty)

    Sign convention is drawer-physical: bale ADDS (cash arrived in drawer),
    vault returns SUBTRACT (cash left drawer). Compare against Eunice's manual
    cash count at close to get variance.
    """
    return round(
        opening_cash
        + from_dispatches - dispatches_out
        + from_cashier
        + bale_peso + inter_branch_in - inter_branch_out - vault_returns
        + cheques_cleared - expenses,
        2,
    )
