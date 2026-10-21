from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .calculation import labor_cost

LABOR_RATE_FIELDS = ("gross_minimum_wage",)


class EkapLaborRate(models.Model):
    """Minimum gross wage of a period (the base of the labour floor).

    Kept as a dated record instead of a field on the calculation so a tender bid in
    2027 is checked against the wage that was valid THEN.
    """

    _name = "ekap.labor.rate"
    _description = "Minimum Wage Period"
    _order = "date_from desc"

    name = fields.Char(compute="_compute_name", store=True)
    gross_minimum_wage = fields.Monetary(string="Gross Minimum Wage", required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date()
    source = fields.Char(required=True, help="e.g. Minimum Wage Fixing Commission decision / Official Gazette.")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    active = fields.Boolean(default=True)
    note = fields.Text()

    _period_valid = models.Constraint(
        "CHECK(date_to IS NULL OR date_to >= date_from)",
        "The end date cannot precede the start date.",
    )
    _unique_date_from_company = models.Constraint(
        "unique(date_from, company_id)",
        "Two minimum wage periods cannot share the same start date.",
    )

    @api.depends("date_from", "date_to", "gross_minimum_wage")
    def _compute_name(self):
        for rate in self:
            rate.name = "%s → %s" % (rate.date_from, rate.date_to or "…")

    @api.model
    def get_rate(self, date=None, company=None):
        """The wage valid on ``date``; raises when the period is not defined."""
        date = date or fields.Date.context_today(self)
        company = company or self.env.company
        rate = self.search(
            [
                ("company_id", "=", company.id),
                ("date_from", "<=", date),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", date),
            ],
            limit=1,
        )
        if not rate:
            raise UserError(
                _("No minimum wage period is defined (%s). The labour calculation cannot run.", date)
            )
        return rate


class EkapLaborCalc(models.Model):
    """The labour floor of a tender: the arithmetic of the KİK labour module.

    KGT 79.7: for personnel-based tenders the KİK tool is mandatory and its output
    (3% contract and general expenses included) is the minimum unit price. This
    record mirrors that arithmetic so the bid can be checked before submission.
    """

    _name = "ekap.labor.calc"
    _description = "Labour Minimum Cost Calculation"
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    tender_id = fields.Many2one("ekap.tender", string="Tender", ondelete="set null")
    rate_id = fields.Many2one(
        "ekap.labor.rate",
        string="Minimum Wage Period",
        required=True,
        default=lambda self: self._default_rate(),
    )
    worker_count = fields.Integer(string="Worker Count", default=1, required=True)
    month_count = fields.Integer(string="Duration (Months)", default=12, required=True)
    employer_ss_reduction = fields.Boolean(
        string="5-Point Reduction",
        default=True,
        help="Law 5510: a 5-point reduction applies to the employer social security share.",
    )
    transport_monthly = fields.Monetary(string="Transport (Monthly)")
    clothing_yearly = fields.Monetary(string="Clothing (Yearly)")
    overtime_hours_monthly = fields.Float(string="Overtime (Hours/Month)", digits=(6, 1))
    overtime_coefficient = fields.Float(string="Overtime Coefficient", digits=(4, 2), default=1.5)
    monthly_working_hours = fields.Integer(string="Monthly Working Hours", default=225)

    employer_social_security = fields.Monetary(compute="_compute_cost", string="Employer Social Security", store=True)
    meal = fields.Monetary(compute="_compute_cost", string="Meal", store=True)
    clothing_monthly = fields.Monetary(compute="_compute_cost", string="Clothing (Monthly)", store=True)
    overtime = fields.Monetary(compute="_compute_cost", string="Overtime", store=True)
    total_without_profit = fields.Monetary(compute="_compute_cost", string="Total Without Profit", store=True)
    contract_overhead = fields.Monetary(compute="_compute_cost", string="Contract + Overhead (3%)", store=True)
    minimum_unit_cost = fields.Monetary(
        compute="_compute_cost", string="Minimum Monthly Cost (worker/month)", store=True
    )
    minimum_hourly_cost = fields.Monetary(compute="_compute_cost", string="Minimum Hourly Cost", store=True)
    total_minimum_cost = fields.Monetary(compute="_compute_cost", string="Total Minimum Cost", store=True)

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    note = fields.Text()

    _worker_count_positive = models.Constraint(
        "CHECK(worker_count > 0)",
        "The worker count must be at least 1.",
    )
    _month_count_positive = models.Constraint(
        "CHECK(month_count > 0)",
        "The duration must be at least 1 month.",
    )
    _monthly_hours_positive = models.Constraint(
        "CHECK(monthly_working_hours > 0)",
        "The monthly working hours must be positive.",
    )

    @api.model
    def _default_rate(self):
        return self.env["ekap.labor.rate"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )

    @api.depends("rate_id", "worker_count", "month_count")
    def _compute_name(self):
        for calc in self:
            calc.name = _("%(rate)s · %(workers)s worker(s) · %(months)s month(s)") % {
                "rate": calc.rate_id.name or "—",
                "workers": calc.worker_count,
                "months": calc.month_count,
            }

    def _rates(self):
        Params = self.env["ekap.parameter"]
        codes = (
            "EMPLOYEE_SOCIAL_SECURITY",
            "EMPLOYEE_UNEMPLOYMENT",
            "EMPLOYER_SS_REDUCED",
            "EMPLOYER_SS_FULL",
            "EMPLOYER_UNEMPLOYMENT",
            "MEAL_RATE",
            "CONTRACT_OVERHEAD",
        )
        return {code: Params.get_value(code, company=self.company_id) for code in codes}

    @api.depends(
        "rate_id.gross_minimum_wage",
        "worker_count",
        "month_count",
        "employer_ss_reduction",
        "transport_monthly",
        "clothing_yearly",
        "overtime_hours_monthly",
        "overtime_coefficient",
        "monthly_working_hours",
    )
    def _compute_cost(self):
        for calc in self:
            if not calc.rate_id or not calc.worker_count or not calc.month_count:
                calc.employer_social_security = calc.meal = calc.clothing_monthly = calc.overtime = 0.0
                calc.total_without_profit = calc.contract_overhead = 0.0
                calc.minimum_unit_cost = calc.minimum_hourly_cost = calc.total_minimum_cost = 0.0
                continue
            result = labor_cost(
                calc.rate_id.gross_minimum_wage,
                calc._rates(),
                worker_count=calc.worker_count,
                month_count=calc.month_count,
                employer_ss_reduction=calc.employer_ss_reduction,
                transport_monthly=calc.transport_monthly,
                clothing_yearly=calc.clothing_yearly,
                overtime_hours_monthly=calc.overtime_hours_monthly,
                overtime_coefficient=calc.overtime_coefficient,
                monthly_working_hours=calc.monthly_working_hours,
            )
            calc.employer_social_security = result["employer_social_security"]
            calc.meal = result["meal"]
            calc.clothing_monthly = result["clothing_monthly"]
            calc.overtime = result["overtime"]
            calc.total_without_profit = result["total_without_profit"]
            calc.contract_overhead = result["contract_overhead"]
            calc.minimum_unit_cost = result["minimum_unit_cost"]
            calc.minimum_hourly_cost = result["minimum_hourly_cost"]
            calc.total_minimum_cost = result["total_minimum_cost"]
