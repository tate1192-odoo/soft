from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Every rate the calculation engine reads. Kept as a selection so a typo in a
# data file cannot invent a new parameter, and so the screens can group them.
PARAMETER_CODES = [
    ("WORKS_N_OTHER", "Construction works limit value coefficient (other works)"),
    ("WORKS_N_SUPERSTRUCTURE", "Construction works limit value coefficient (superstructure/installations)"),
    ("ANALYSIS_PROFIT_OVERHEAD", "Profit and overhead rate of public analyses"),
    ("NEW_UNIT_PRICE_PROFIT", "Profit rate of a new unit price (YİGŞ art.22)"),
    ("NEW_UNIT_PRICE_OVERHEAD", "Overhead rate of a new unit price (YİGŞ art.22)"),
    ("PROVISIONAL_SECURITY", "Provisional security rate"),
    ("FINAL_SECURITY", "Final security rate"),
    ("FINAL_SECURITY_BELOW_LIMIT", "Works: final security rate of a bid below the limit value (on the approximate cost)"),
    ("STAMP_DUTY_AWARD", "Stamp duty rate of the award decision"),
    ("STAMP_DUTY_CONTRACT", "Stamp duty rate of the contract"),
    ("VAT", "Value added tax rate"),
    ("CONTRACT_OVERHEAD", "Contract and overhead rate (in the labour calculation)"),
    ("EMPLOYEE_SOCIAL_SECURITY", "Employee social security share"),
    ("EMPLOYEE_UNEMPLOYMENT", "Employee unemployment insurance share"),
    ("EMPLOYER_SS_REDUCED", "Employer social security share (5-point reduction)"),
    ("EMPLOYER_SS_FULL", "Employer social security share (no reduction)"),
    ("EMPLOYER_UNEMPLOYMENT", "Employer unemployment insurance share"),
    ("MEAL_RATE", "Meal rate (on the daily gross wage)"),
    ("SERVICE_R_VEHICLE_RENTAL", "Service: vehicle rental limit value coefficient (R)"),
    ("SERVICE_R_INFORMATION_SYSTEMS", "Service: information systems limit value coefficient (R)"),
    ("SERVICE_R_CATERING", "Service: catering with material limit value coefficient (R)"),
    ("SERVICE_R_ENGINEERING", "Service: engineering limit value coefficient (R)"),
    ("SERVICE_R_INSURANCE", "Service: insurance limit value coefficient (R)"),
    ("SERVICE_R_TRANSPORT", "Service: transport limit value coefficient (R)"),
    ("SERVICE_R_OTHER", "Service: other limit value coefficient (R)"),
]


class EkapParameter(models.Model):
    """A rate or coefficient with a validity period.

    Nothing in the calculation engine hardcodes a rate: a rule that changes yearly
    (the construction coefficient N, the service coefficients R, stamp duty, SGK
    shares) lives here with the date it became valid and the source it came from,
    so a calculation made in 2027 can still be explained/replayed.
    """

    _name = "ekap.parameter"
    _description = "Tender Parameter (rate / coefficient)"
    _order = "code, date_from desc"
    _check_company_auto = True

    code = fields.Selection(PARAMETER_CODES, required=True, index=True)
    value = fields.Float(digits=(16, 6), required=True)
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date()
    source = fields.Char(
        required=True,
        help="Source of the value (legislation article / KİK announcement / SGK).",
    )
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company",
        ondelete="cascade",
        help="Leave empty for the value that applies to every company.",
    )
    active = fields.Boolean(default=True)
    name = fields.Char(compute="_compute_name", store=True)

    _value_positive = models.Constraint(
        "CHECK(value >= 0)",
        "The rate/coefficient cannot be negative.",
    )
    _period_valid = models.Constraint(
        "CHECK(date_to IS NULL OR date_to >= date_from)",
        "The end date cannot precede the start date.",
    )

    @api.depends("code", "date_from", "date_to")
    def _compute_name(self):
        labels = dict(self._fields["code"]._description_selection(self.env))
        for param in self:
            period = param.date_from and str(param.date_from) or ""
            if param.date_to:
                period = "%s → %s" % (period, param.date_to)
            param.name = "%s (%s)" % (labels.get(param.code, param.code), period)

    @api.constrains("code", "date_from", "date_to", "company_id")
    def _check_period_overlap(self):
        """Two values for the same code must not claim the same day.

        Overlaps would make ``get_value`` depend on the order of the records, i.e.
        a bid could be priced with whichever rate happened to be read first.
        """
        for param in self:
            domain = [
                ("id", "!=", param.id),
                ("code", "=", param.code),
                ("company_id", "=", param.company_id.id),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", param.date_from),
            ]
            if param.date_to:
                domain.append(("date_from", "<=", param.date_to))
            if self.search_count(domain):
                raise UserError(
                    _(
                        "A second value exists for this code over the same period: %s. "
                        "Update the existing record or narrow the date range.",
                        param.code,
                    )
                )

    @api.model
    def get_value(self, code, date=None, company=None):
        """Return the value of ``code`` valid on ``date``.

        A missing value raises instead of falling back to a guess: a silently
        defaulted rate would produce a wrong bid that looks correct on screen.
        """
        date = date or fields.Date.context_today(self)
        company = company or self.env.company
        base_domain = [
            ("code", "=", code),
            ("active", "=", True),
            ("date_from", "<=", date),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", date),
        ]
        # A company-specific value always wins over the global fallback. Searching
        # twice avoids relying on the database's NULL ordering.
        params = self.search(
            base_domain + [("company_id", "=", company.id)],
            order="date_from desc",
            limit=1,
        )
        if not params:
            params = self.search(
                base_domain + [("company_id", "=", False)],
                order="date_from desc",
                limit=1,
            )
        if not params:
            raise UserError(
                _(
                    "Tender parameter not found: %(code)s (%(date)s). "
                    "A bid is never priced with a default rate; define the parameter.",
                    code=code,
                    date=date,
                )
            )
        return params.value

    @api.model
    def get_value_or_false(self, code, date=None, company=None):
        """Same as :meth:`get_value` but returns ``False`` instead of raising.

        Used by the informational fields on screen (a wrong rate must block a
        saved calculation, not the rendering of an empty record).
        """
        self = self.sudo()
        try:
            return self.get_value(code, date=date, company=company)
        except UserError:
            return False
