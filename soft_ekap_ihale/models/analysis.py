from odoo import api, fields, models

# The kinds of input a public analysis is made of. The distinction matters when an
# abnormally low explanation is prepared: the commission asks for the
# analysis inputs except labour, and up to 15% of the inputs may be left out (KGT 45.1.1).
ANALYSIS_LINE_TYPES = [
    ("material", "Material"),
    ("labour", "Labour"),
    ("machine", "Machine / Vehicle"),
    ("transport", "Transport"),
    ("other", "Other"),
]


class EkapAnalysis(models.Model):
    """A public (or the firm's own) analysis of one work item.

    Example: 15.150.1002 "Ready-mixed C 12/15 concrete produced in a batching
    plant or purchased and placed with a concrete pump" — its inputs are the
    ready-mixed concrete, the pump hour and labour, and the total carries the 25%
    profit and general expenses of the public analyses.
    """

    _name = "ekap.analysis"
    _description = "Tender Analysis"
    _inherit = ["mail.thread"]
    _order = "code, name"

    code = fields.Char(string="Analysis Code", required=True, index=True)
    name = fields.Char(string="Description", required=True)
    uom_id = fields.Many2one("uom.uom", string="Unit", required=True)
    kind = fields.Selection(
        [("public", "Public analysis"), ("company", "Company analysis"), ("new_unit_price", "New unit price")],
        default="public",
        required=True,
    )
    profit_overhead_rate = fields.Float(
        string="Profit and overhead",
        digits=(6, 4),
        default=lambda self: self.env["ekap.parameter"].get_value_or_false("ANALYSIS_PROFIT_OVERHEAD") or 0.0,
        help="Rate added on top of the total of a public analysis (default: parameter "
        "ANALYSIS_PROFIT_OVERHEAD = 25%). New unit prices use the caps of YİGŞ art.22 "
        "instead.",
    )
    line_ids = fields.One2many("ekap.analysis.line", "analysis_id", string="Inputs")
    total_without_profit = fields.Monetary(compute="_compute_totals", store=True, string="Total without profit")
    total_amount = fields.Monetary(compute="_compute_totals", store=True, string="Analysis amount")
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)
    note = fields.Text()

    _code_company_uniq = models.Constraint(
        "unique(code, company_id)",
        "The same analysis code cannot be defined twice.",
    )

    @api.depends("line_ids.price_subtotal", "profit_overhead_rate")
    def _compute_totals(self):
        for analysis in self:
            without_profit = sum(analysis.line_ids.mapped("price_subtotal"))
            analysis.total_without_profit = without_profit
            analysis.total_amount = without_profit * (1.0 + analysis.profit_overhead_rate)


class EkapAnalysisLine(models.Model):
    _name = "ekap.analysis.line"
    _description = "Tender Analysis Input"
    _order = "analysis_id, sequence, id"

    analysis_id = fields.Many2one(
        "ekap.analysis", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(ANALYSIS_LINE_TYPES, string="Input Type", required=True)
    name = fields.Char(string="Input", required=True)
    reference = fields.Char(string="Item / Reference", help="Public item number or company reference.")
    uom_id = fields.Many2one("uom.uom", string="Unit")
    quantity = fields.Float(string="Quantity", digits="Product Unit of Measure", default=1.0)
    unit_price = fields.Monetary(string="Unit Price")
    price_subtotal = fields.Monetary(compute="_compute_subtotal", store=True, string="Amount")
    currency_id = fields.Many2one(related="analysis_id.currency_id", string="Currency")
    company_id = fields.Many2one(related="analysis_id.company_id", store=True, index=True)
    note = fields.Char()

    @api.depends("quantity", "unit_price")
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.unit_price

    def action_open_analysis(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "ekap.analysis",
            "res_id": self.analysis_id.id,
            "view_mode": "form",
            "target": "current",
        }
