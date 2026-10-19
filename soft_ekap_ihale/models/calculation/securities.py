"""Securities, stamp duty and VAT arithmetic.

References: Law 4734 art.33 (provisional security, not less than 3% of the bid)
and art.43 (final security 6%; for a construction bid below the limit value the
security is computed on the approximate cost — the rate is a parameter, 9% by
default), Stamp Duty Law 488, table (1) (award decision 5.69‰, contract 9.48‰)
and VAT Law 3065 (20%).
"""


class SecurityCalculationError(ValueError):
    """Raised when a security or tax cannot be computed."""


def securities(
    bid_amount,
    provisional_rate,
    final_rate,
    approximate_cost=None,
    limit_value=None,
    works=False,
    final_below_limit_rate=None,
):
    """Return the provisional and final securities of a bid.

    A construction bid below the limit value carries a final security computed on
    the approximate cost instead of the bid amount, which is why ``approximate_cost``
    and ``final_below_limit_rate`` are needed to answer that case.
    """
    bid = float(bid_amount or 0.0)
    if bid <= 0:
        raise SecurityCalculationError("The bid amount must be positive.")
    provisional = bid * float(provisional_rate)
    below_limit = bool(
        works and limit_value and approximate_cost and final_below_limit_rate and bid < float(limit_value)
    )
    if below_limit:
        final = float(approximate_cost) * float(final_below_limit_rate)
        rate = float(final_below_limit_rate)
        basis = "on the approximate cost (Law 4734 art.43, works bid below the limit value)"
    else:
        final = bid * float(final_rate)
        rate = float(final_rate)
        basis = "on the bid amount (Law 4734 art.43)"
    return {
        "provisional_security": provisional,
        "final_security": final,
        "final_rate": rate,
        "final_basis": basis,
    }


def stamp_duties(award_amount, contract_price, award_rate, contract_rate):
    """Stamp duty of the award decision and of the contract (488 s. Kanun)."""
    return {
        "award_stamp_duty": float(award_amount or 0.0) * float(award_rate),
        "contract_stamp_duty": float(contract_price or 0.0) * float(contract_rate),
    }


def vat_excluded(amount, rate):
    """VAT-exclusive amount of a VAT-inclusive one."""
    rate = float(rate or 0.0)
    if rate <= -1:
        raise SecurityCalculationError("Invalid VAT rate.")
    return float(amount or 0.0) / (1.0 + rate)


def vat_included(amount, rate):
    """VAT-inclusive amount of a VAT-exclusive one."""
    return float(amount or 0.0) * (1.0 + float(rate or 0.0))
