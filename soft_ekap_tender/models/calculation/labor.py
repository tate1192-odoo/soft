"""Labour minimum cost — the floor of a personnel-based
service tender.

KGT 79.7 makes the KİK "Labour Calculation Module" mandatory for tenders based on
employing personnel, and the resulting unit prices are the minimum ones with the
3% contract and general expenses included. This module rebuilds that arithmetic so
a bid can be checked BEFORE it is submitted: the tender's price may not fall below
the floor (KGT 79.5).

Components (per worker, per month):
    gross minimum wage
  + employer SGK share + employer unemployment insurance
  + meal (6% of the daily gross wage, i.e. ~6% of the monthly gross)
  + road, clothing (annual amount / 12)
  + overtime (hourly wage × 1.5 × the hours in the period)
  + 3% contract and general expenses on all of the above
"""


class LaborCalculationError(ValueError):
    """Raised when the labour floor cannot be computed."""


def labor_cost(
    gross_minimum_wage,
    rates,
    worker_count=1,
    month_count=1,
    employer_ss_reduction=True,
    transport_monthly=0.0,
    clothing_yearly=0.0,
    overtime_hours_monthly=0.0,
    overtime_coefficient=1.5,
    monthly_working_hours=225,
):
    """Return the labour floor of one worker-month and its breakdown.

    :param rates: mapping code → value, as returned by
        ``ekap.labor.calc._rates()``; the codes are the ones documented in the
        report (ISVEREN_SGK_*, ISCI_*, MEAL_RATE, CONTRACT_OVERHEAD).
    :return: dict with the components, the month total per worker, the grand total
        and the hourly equivalent (used by the service price schedules).
    """
    gross = float(gross_minimum_wage or 0.0)
    if gross <= 0:
        raise LaborCalculationError("The gross minimum wage must be positive.")
    worker_count = int(worker_count or 0)
    month_count = int(month_count or 0)
    if worker_count <= 0 or month_count <= 0:
        raise LaborCalculationError("The worker count and the duration (months) must be at least 1.")

    employer_rate = rates["EMPLOYER_SS_REDUCED" if employer_ss_reduction else "EMPLOYER_SS_FULL"]
    employer_rate += rates["EMPLOYER_UNEMPLOYMENT"]
    employer_social_security = gross * employer_rate
    meal = gross * rates["MEAL_RATE"]
    clothing_monthly = float(clothing_yearly or 0.0) / 12.0
    hourly_wage = gross / float(monthly_working_hours)
    overtime = (
        hourly_wage * float(overtime_coefficient) * float(overtime_hours_monthly or 0.0)
    )

    total_without_profit = (
        gross
        + employer_social_security
        + meal
        + float(transport_monthly or 0.0)
        + clothing_monthly
        + overtime
    )
    contract_overhead = total_without_profit * rates["CONTRACT_OVERHEAD"]
    worker_month_cost = total_without_profit + contract_overhead

    return {
        "gross_minimum_wage": gross,
        "employer_social_security": employer_social_security,
        "employer_ss_rate": employer_rate,
        "meal": meal,
        "yol": float(transport_monthly or 0.0),
        "clothing_monthly": clothing_monthly,
        "overtime": overtime,
        "hourly_wage": hourly_wage,
        "total_without_profit": total_without_profit,
        "contract_overhead": contract_overhead,
        # The floor of ONE worker for ONE month (KGT 79.7), 3% included.
        "minimum_unit_cost": worker_month_cost,
        "minimum_hourly_cost": worker_month_cost / float(monthly_working_hours),
        "total_minimum_cost": worker_month_cost * worker_count * month_count,
        "worker_count": worker_count,
        "month_count": month_count,
    }
