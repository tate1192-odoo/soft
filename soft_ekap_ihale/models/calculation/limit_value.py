"""Limit value and abnormally low bid test.

Construction works — Public Procurement General Communiqué (KGT) 45.1.1: the bids outside
[approximate cost × 0.40, approximate cost × 1.20] are discarded, Tort1 is the
arithmetic mean of the rest, sigma their sample standard deviation (n-1), Tort2
the mean of the bids inside [Tort1 - sigma, Tort1 + sigma], C = Tort2 / YM, K is
read from the piecewise rule below and SD = (K × Tort2) / (C × N). SD can never
be smaller than 40% of the approximate cost. The n-1 denominator follows the
formula printed in KGT 45.1.1 and the official worked example.

Service procurement (not personnel based) — KGT 79.1.2:
SD = ((YM + ΣTn) / (n + 1)) × R, where the bids below 60% of YM and above YM are
left out of the sum.

Goods procurement has no limit value: the commission decides on the "important
offer components" (KGT 62/A), which is why :func:`check_abnormally_low` refuses to
judge a goods tender by a limit value.
"""

from statistics import mean, stdev

# KGT 45.1.1 — the cuts applied before the average is taken.
WORKS_LOWER_RATIO = 0.40
WORKS_UPPER_RATIO = 1.20
# KGT 45.1.1 — SD may not fall below this share of the approximate cost.
WORKS_SD_FLOOR_RATIO = 0.40
# KGT 79.1.2 — the bids taken into the service sum.
SERVICES_LOWER_RATIO = 0.60


class CalculationError(ValueError):
    """Raised when the inputs cannot produce a legally meaningful result."""


def _positive(value, label):
    value = float(value or 0.0)
    if value <= 0:
        raise CalculationError("%s must be positive." % label)
    return value


def _coefficient_k(c):
    """K of KGT 45.1.1."""
    if c < 0.60:
        return c
    if c <= 1.00:
        return (3.2 * c - c**2 - 0.6) / (c + 1)
    return (c**2 - 0.8 * c + 1.4) / (c + 1)


def limit_value_works(approximate_cost, bids, n_coefficient=1.20, detail=False):
    """Limit value of a construction tender (KGT 45.1.1).

    :param approximate_cost: approximate cost (YM)
    :param bids: bid amounts of the tender, any order
    :param n_coefficient: coefficient N of KGT 45.1.1.1 (1.00 for superstructure,
        electrical, mechanical, telecommunication works, 1.20 otherwise)
    :return: the limit value, or a dict with the intermediate values when
        ``detail`` is set (the report shows them, so the reader can check the rule).
    """
    ym = _positive(approximate_cost, "Approximate cost")
    n = _positive(n_coefficient, "N coefficient")
    bids = sorted(float(b) for b in bids if b)
    if not bids:
        raise CalculationError("At least one bid is required to compute the limit value.")

    valid = [b for b in bids if ym * WORKS_LOWER_RATIO <= b <= ym * WORKS_UPPER_RATIO]
    if not valid:
        raise CalculationError(
            "No valid bid inside the 40%-120% band of the approximate cost; the limit value cannot be computed."
        )

    tort1 = mean(valid)
    sigma = stdev(valid) if len(valid) > 1 else 0.0
    if sigma:
        band = [b for b in valid if tort1 - sigma <= b <= tort1 + sigma]
    else:
        band = list(valid)
    tort2 = mean(band)

    c = tort2 / ym
    k = _coefficient_k(c)
    sd = (k * tort2) / (c * n)
    floor = ym * WORKS_SD_FLOOR_RATIO
    sd = max(sd, floor)

    if not detail:
        return sd
    return {
        "approximate_cost": ym,
        "bids": bids,
        "valid_bids": valid,
        "tort1": tort1,
        "sigma": sigma,
        "band_bids": band,
        "tort2": tort2,
        "c": c,
        "k": k,
        "sd_raw": (k * tort2) / (c * n),
        "sd_floor": floor,
        "limit_value": sd,
    }


def limit_value_services(approximate_cost, bids, r_coefficient, detail=False):
    """Limit value of a service tender (KGT 79.1.2).

    ``R`` is the yearly "limit value coefficient" published per service kind
    (KİK decision); it must come from ``ekap.parameter`` so the year it belongs to
    stays visible.
    """
    ym = _positive(approximate_cost, "Approximate cost")
    r = _positive(r_coefficient, "R coefficient")
    bids = sorted(float(b) for b in bids if b)
    valid = [b for b in bids if ym * SERVICES_LOWER_RATIO <= b <= ym]
    if not valid:
        raise CalculationError(
            "No bid between 60% of the approximate cost and the approximate cost itself; "
            "the limit value cannot be computed."
        )
    sd = ((ym + sum(valid)) / (len(valid) + 1)) * r
    if not detail:
        return sd
    return {
        "approximate_cost": ym,
        "bids": bids,
        "valid_bids": valid,
        "r_coefficient": r,
        "limit_value": sd,
    }


def check_abnormally_low(bid, limit_value, tender_type="works", explanation_threshold_exceeded=False):
    """Decide whether ``bid`` is under the limit value, i.e. needs an explanation.

    :param explanation_threshold_exceeded: 4734 m.38 last paragraph — for tenders whose
        approximate cost is below half of the threshold, and for certain service
        kinds, an under-limit bid is REJECTED instead of explained. Pass ``True``
        when the tender falls in that group.
    :return: dict with ``abnormally_low`` (bool), ``status`` and a human-readable ``message``.
    """
    if tender_type == "goods":
        return {
            "abnormally_low": False,
            "status": "commission_assessment",
            "message": (
                "Goods procurement has no limit value formula; the commission decides on the "
                "abnormally low bid using the significant cost components (KGT 62/A)."
            ),
        }
    if not limit_value:
        return {
            "abnormally_low": False,
            "status": "limit_value_unknown",
            "message": "The abnormally low check was skipped because no limit value is set.",
        }
    below = float(bid) < float(limit_value)
    if not below:
        return {
            "abnormally_low": False,
            "status": "above_limit_value",
            "message": "The bid is not below the limit value.",
        }
    if explanation_threshold_exceeded:
        return {
            "abnormally_low": True,
            "status": "rejected",
            "message": (
                "The bid is below the limit value and is rejected without explanation in "
                "such tenders (Law 4734 art.38, last paragraph)."
            ),
        }
    return {
        "abnormally_low": True,
        "status": "explanation_required",
        "message": (
            "The bid is below the limit value: the contracting authority will request an "
            "abnormally low bid explanation (at least 5 working days for works, 3 for goods/services)."
        ),
    }
