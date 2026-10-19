from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .calculation import limit_value_services, limit_value_works


class EkapLimitValueWizard(models.TransientModel):
    """Limit value calculator, the same arithmetic the KİK tool runs.

    KİK publishes its own calculation tools; this wizard lets the firm reproduce
    the figures with its own parameter set (a value read from the wrong year would
    silently move the limit value).
    """

    _name = "ekap.limit.value.wizard"
    _description = "Limit Value Calculation"

    tender_id = fields.Many2one(
        "ekap.tender", required=True, ondelete="cascade", string="Tender"
    )
    tender_type = fields.Selection(related="tender_id.tender_type", string="Type")
    currency_id = fields.Many2one(related="tender_id.currency_id", string="Currency")
    company_id = fields.Many2one(related="tender_id.company_id")
    approximate_cost = fields.Monetary(
        string="Approximate Cost", required=True, default=lambda self: self.tender_id.approximate_cost
    )
    n_coefficient = fields.Float(
        string="N Coefficient", digits=(6, 4), default=lambda self: self.tender_id.n_coefficient or 1.20
    )
    r_coefficient = fields.Float(
        string="R Coefficient", digits=(6, 4), default=lambda self: self.tender_id.r_coefficient or 0.78
    )
    bid_text = fields.Text(
        string="Bid Amounts",
        required=True,
        help="Enter the bids of the tender, one amount per line. "
        "Local notation (12.345,67) and dotted notation (12345.67) are both accepted.",
    )

    result_html = fields.Html(
        compute="_compute_result", readonly=True, sanitize=False, string="Result"
    )
    limit_value = fields.Monetary(compute="_compute_result", string="Limit Value")

    @api.model
    def _parse_amounts(self, text):
        """Read one amount per line, accepting local and plain notation.

        "12.345,67" (dot groups thousands, comma is the decimal separator) and
        "12345.67" are both accepted; a lone dot followed by three digits and at
        most three leading digits ("1.250") is read as a thousands separator,
        because that is how operators paste amounts locally.
        """
        amounts = []
        for raw in (text or "").replace(";", "\n").splitlines():
            line = raw.strip().replace(" ", "").replace("\u00a0", "")
            if not line:
                continue
            if "," in line:
                line = line.replace(".", "").replace(",", ".")
            elif "." in line:
                head, _sep, tail = line.rpartition(".")
                if "." in head or (len(tail) == 3 and 0 < len(head) <= 3):
                    line = line.replace(".", "")
            try:
                amounts.append(float(line))
            except ValueError as exc:
                raise UserError(_("Amount not understood: %s", raw)) from exc
        if not amounts:
            raise UserError(_("Enter at least one bid amount."))
        return amounts

    @api.depends("approximate_cost", "n_coefficient", "r_coefficient", "bid_text", "tender_type")
    def _compute_result(self):
        for wizard in self:
            wizard.limit_value = 0.0
            wizard.result_html = False
            if not wizard.approximate_cost or not wizard.bid_text:
                continue
            bids = wizard._parse_amounts(wizard.bid_text)
            if wizard.tender_type == "services":
                result = limit_value_services(
                    wizard.approximate_cost, bids, wizard.r_coefficient, detail=True
                )
                rows = [
                    (_("Approximate cost"), result["approximate_cost"]),
                    (_("Valid bids"), ", ".join("%.2f" % t for t in result["valid_bids"])),
                    (_("R coefficient"), result["r_coefficient"]),
                    (_("Limit value"), result["limit_value"]),
                ]
            else:
                result = limit_value_works(
                    wizard.approximate_cost, bids, wizard.n_coefficient, detail=True
                )
                rows = [
                    (_("Approximate cost"), result["approximate_cost"]),
                    (_("Tort1"), result["tort1"]),
                    (_("Standard deviation (σ)"), result["sigma"]),
                    (_("Tort2"), result["tort2"]),
                    (_("C = Tort2 / YM"), result["c"]),
                    (_("K"), result["k"]),
                    (_("N coefficient"), wizard.n_coefficient),
                    (_("Computed limit value"), result["sd_raw"]),
                    (_("Floor (AC × 40%)"), result["sd_floor"]),
                    (_("Limit value"), result["limit_value"]),
                ]
            body = "".join(
                "<tr><td>%s</td><td class='text-end'>%s</td></tr>"
                % (
                    label,
                    "%.4f" % value if isinstance(value, float) and value < 10 else "%.2f" % value
                    if isinstance(value, float)
                    else value,
                )
                for label, value in rows
            )
            wizard.limit_value = result["limit_value"]
            wizard.result_html = "<table class='table table-sm'>%s</table>" % body

    def action_apply(self):
        """Store the computed limit value on the tender."""
        self.ensure_one()
        if not self.limit_value:
            raise UserError(_("The limit value has not been computed."))
        self.tender_id.write(
            {
                "limit_value": self.limit_value,
                "limit_value_source": "computed",
                "n_coefficient": self.n_coefficient,
                "r_coefficient": self.r_coefficient,
            }
        )
        self.tender_id.message_post(
            body=_("Limit value computed and written on the tender: %s", "%0.2f" % self.limit_value)
        )
        return {"type": "ir.actions.act_window_close"}
