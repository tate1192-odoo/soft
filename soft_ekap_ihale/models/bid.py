from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .calculation import (
    check_abnormally_low,
    securities,
    stamp_duties,
)

BID_STATES = [
    ("draft", "In Preparation"),
    ("ready", "Ready"),
    ("submitted", "Submitted"),
    ("won", "Won"),
    ("lost", "Lost"),
    ("cancelled", "Cancelled"),
]


class EkapBid(models.Model):
    """The company's own offer for a tender (one bid per attempt)."""

    _name = "ekap.bid"
    _description = "Tender Bid"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Reference", required=True, default="/", copy=False, index=True
    )
    tender_id = fields.Many2one(
        "ekap.tender", required=True, ondelete="cascade", index=True, string="Tender"
    )
    state = fields.Selection(BID_STATES, default="draft", required=True, tracking=True)
    tender_type = fields.Selection(related="tender_id.tender_type", string="Type", store=True)
    limit_value = fields.Monetary(related="tender_id.limit_value", string="Limit Value")
    approximate_cost = fields.Monetary(related="tender_id.approximate_cost", string="Approximate Cost")
    personnel_based = fields.Boolean(related="tender_id.personnel_based", string="Personnel Based")

    bulk_discount_rate = fields.Float(
        string="Discount Rate (%)",
        digits=(6, 2),
        help="Bulk discount applied to the public unit prices. The 'Apply discount' "
        "button rewrites the offer unit price of every line.",
    )
    line_ids = fields.One2many("ekap.bid.line", "bid_id", string="Bid Items")

    authority_total = fields.Monetary(compute="_compute_totals", string="Authority Amount", store=True)
    bid_total = fields.Monetary(compute="_compute_totals", string="Bid Amount", store=True)

    abnormally_low = fields.Boolean(
        compute="_compute_controls", string="Abnormally Low Bid", store=True
    )
    abnormally_low_status = fields.Char(compute="_compute_controls", string="Abnormally Low Status", store=True)
    explanation_ready = fields.Boolean(
        string="Explanation Ready",
        help="A bid below the limit value does not count as submitted before the "
        "explanation file is ready.",
    )
    labor_warning = fields.Char(compute="_compute_controls", string="Labour Check", store=True)

    provisional_security = fields.Monetary(compute="_compute_securities", string="Provisional Security")
    final_security = fields.Monetary(compute="_compute_securities", string="Final Security")
    final_security_basis = fields.Char(
        compute="_compute_securities", string="Final Security Basis"
    )
    award_stamp_duty = fields.Monetary(compute="_compute_stamp_duty", string="Award Stamp Duty")
    contract_stamp_duty = fields.Monetary(compute="_compute_stamp_duty", string="Contract Stamp Duty")
    tax_warning = fields.Char(compute="_compute_stamp_duty", string="Tax Check")

    submitted_on = fields.Datetime(string="Submission Date", readonly=True, copy=False)
    ekey_sent = fields.Boolean(string="e-Key Sent", tracking=True)
    submission_method = fields.Selection(
        [("ekap_client", "EKAP client + e-signature"), ("direct", "Direct procurement / other")],
        default="ekap_client",
        required=True,
        string="Submission Method",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    note = fields.Html()

    _bid_total_positive = models.Constraint(
        "CHECK(bid_total >= 0)",
        "The bid amount cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ekap.bid") or "/"
        return super().create(vals_list)

    @api.depends("line_ids.price_subtotal", "line_ids.item_id.authority_amount")
    def _compute_totals(self):
        for bid in self:
            bid.bid_total = sum(bid.line_ids.mapped("price_subtotal"))
            bid.authority_total = sum(bid.line_ids.mapped("item_id.authority_amount"))

    def _rates(self, codes):
        """Read the parameters valid today, once per code."""
        Params = self.env["ekap.parameter"]
        return {code: Params.get_value(code, company=self.company_id) for code in codes}

    @api.depends(
        "bid_total",
        "limit_value",
        "tender_type",
        "line_ids.offer_unit_price",
        "tender_id.reject_without_explanation",
        "tender_id.labor_calc_id.minimum_unit_cost",
    )
    def _compute_controls(self):
        for bid in self:
            bid.abnormally_low = False
            bid.abnormally_low_status = False
            bid.labor_warning = False
            if not bid.bid_total:
                continue
            result = check_abnormally_low(
                bid.bid_total,
                bid.limit_value,
                tender_type=bid.tender_type or "works",
                explanation_threshold_exceeded=bid.tender_id.reject_without_explanation,
            )
            bid.abnormally_low = result["abnormally_low"]
            bid.abnormally_low_status = result["message"]
            if bid.personnel_based:
                labor = bid.tender_id.labor_calc_id
                if not labor:
                    bid.labor_warning = _("No labour calculation; the minimum cost could not be checked.")
                else:
                    items = bid.line_ids.filtered(lambda l: l.item_id.uom_id)
                    monthly_items = items.filtered(
                        lambda l: (l.item_id.uom_id.name or "").lower().startswith(
                            ("ay", "month")
                        )
                    )
                    to_check = monthly_items or bid.line_ids
                    minimum = labor.minimum_unit_cost
                    below = to_check.filtered(
                        lambda l, minimum=minimum: l.offer_unit_price
                        and l.offer_unit_price < minimum
                    )
                    if below:
                        bid.labor_warning = _(
                            "The unit price of %(items)s item(s) is below the labour minimum "
                            "(%(minimum)s).",
                            items=len(below),
                            minimum="%.2f" % labor.minimum_unit_cost,
                        )

    @api.depends("bid_total", "tender_type", "limit_value", "approximate_cost")
    def _compute_securities(self):
        Params = self.env["ekap.parameter"]
        for bid in self:
            if not bid.bid_total:
                bid.provisional_security = bid.final_security = 0.0
                bid.final_security_basis = False
                continue
            codes = ["PROVISIONAL_SECURITY", "FINAL_SECURITY"]
            works_below_limit = (
                bid.tender_type == "works"
                and bid.limit_value
                and bid.approximate_cost
                and bid.bid_total < bid.limit_value
            )
            if works_below_limit:
                codes.append("FINAL_SECURITY_BELOW_LIMIT")
            rates = {
                code: Params.get_value_or_false(code, company=bid.company_id)
                for code in codes
            }
            missing = [code for code, value in rates.items() if value is False]
            if missing:
                bid.provisional_security = bid.final_security = 0.0
                bid.final_security_basis = _("Missing parameter(s): %s.") % ", ".join(missing)
                continue
            result = securities(
                bid.bid_total,
                rates["PROVISIONAL_SECURITY"],
                rates["FINAL_SECURITY"],
                approximate_cost=bid.approximate_cost,
                limit_value=bid.limit_value,
                works=bid.tender_type == "works",
                final_below_limit_rate=rates.get("FINAL_SECURITY_BELOW_LIMIT"),
            )
            bid.provisional_security = result["provisional_security"]
            bid.final_security = result["final_security"]
            bid.final_security_basis = result["final_basis"]

    @api.depends("bid_total")
    def _compute_stamp_duty(self):
        Params = self.env["ekap.parameter"]
        for bid in self:
            if not bid.bid_total:
                bid.award_stamp_duty = bid.contract_stamp_duty = 0.0
                bid.tax_warning = False
                continue
            award_rate = Params.get_value_or_false(
                "STAMP_DUTY_AWARD", company=bid.company_id
            )
            contract_rate = Params.get_value_or_false(
                "STAMP_DUTY_CONTRACT", company=bid.company_id
            )
            missing = [
                code
                for code, value in (
                    ("STAMP_DUTY_AWARD", award_rate),
                    ("STAMP_DUTY_CONTRACT", contract_rate),
                )
                if value is False
            ]
            if missing:
                bid.award_stamp_duty = bid.contract_stamp_duty = 0.0
                bid.tax_warning = _("Missing parameter(s): %s.") % ", ".join(missing)
                continue
            duties = stamp_duties(
                bid.bid_total,
                bid.bid_total,
                award_rate,
                contract_rate,
            )
            bid.award_stamp_duty = duties["award_stamp_duty"]
            bid.contract_stamp_duty = duties["contract_stamp_duty"]
            bid.tax_warning = False

    def action_generate_lines(self):
        """Create one bid line per tender item, carrying the public unit price."""
        for bid in self:
            if bid.line_ids:
                raise UserError(_("The items of this bid are already generated."))
            if not bid.tender_id.item_ids:
                raise UserError(_("The tender has no work item; add them first."))
            bid.line_ids = [
                (
                    0,
                    0,
                    {
                        "item_id": item.id,
                        "offer_unit_price": item.authority_unit_price,
                    },
                )
                for item in bid.tender_id.item_ids
            ]
        return True

    def action_apply_discount(self):
        """Rewrite every unit price as the public one minus the discount."""
        for bid in self:
            for line in bid.line_ids:
                if line.item_id.authority_unit_price:
                    line.offer_unit_price = line.item_id.authority_unit_price * (
                        1.0 - bid.bulk_discount_rate / 100.0
                    )
        return True

    def action_copy_prices_to_tender(self):
        """Write the offer prices back on the tender items (the printed schedule)."""
        for bid in self:
            for line in bid.line_ids:
                line.item_id.offer_unit_price = line.offer_unit_price
        return True

    def _check_required_parameters(self):
        """Block submission when a rate used by the bid is missing.

        The display fields are forgiving (a manager archiving a parameter must
        not make the bid list unreadable); the hard check belongs here, when the
        bid is actually being submitted.
        """
        self.ensure_one()
        codes = [
            "PROVISIONAL_SECURITY",
            "FINAL_SECURITY",
            "STAMP_DUTY_AWARD",
            "STAMP_DUTY_CONTRACT",
        ]
        if (
            self.tender_type == "works"
            and self.limit_value
            and self.approximate_cost
            and self.bid_total
            and self.bid_total < self.limit_value
        ):
            codes.append("FINAL_SECURITY_BELOW_LIMIT")
        Params = self.env["ekap.parameter"]
        for code in codes:
            Params.get_value(code, company=self.company_id)

    def action_submit(self):
        """Mark the bid as submitted — the submission itself happens on EKAP."""
        for bid in self:
            bid._check_required_parameters()
            if not bid.line_ids:
                raise UserError(_("A bid cannot be marked as submitted before its items exist."))
            if bid.abnormally_low and bid.tender_id.reject_without_explanation:
                raise UserError(
                    _(
                        "The bid is below the limit value in a tender that rejects such bids "
                        "without explanation (Law 4734 art.38). It cannot be marked as submitted."
                    )
                )
            if bid.abnormally_low and not bid.explanation_ready:
                raise UserError(
                    _(
                        "The bid is below the limit value. It cannot be marked as submitted "
                        "before the abnormally low explanation is ready."
                    )
                )
            bid.write({"state": "submitted", "submitted_on": fields.Datetime.now()})
        return True

    def action_won(self):
        for bid in self:
            bid.write({"state": "won"})
            vals = {"state": "won"}
            # The winner of our own award is known: fill it in, but never
            # overwrite what the operator typed from the result notice.
            if not bid.tender_id.winning_firm:
                vals["winning_firm"] = bid.company_id.name
            bid.tender_id.write(vals)
        return True

    def action_lost(self):
        for bid in self:
            bid.write({"state": "lost"})
            # A lost bid does not make the tender lost while another bid of
            # the same tender has won.
            other_won = bid.tender_id.bid_ids.filtered(
                lambda other: other.id != bid.id and other.state == "won"
            )
            if not other_won:
                bid.tender_id.write({"state": "lost"})
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})


class EkapBidLine(models.Model):
    """One priced item of the bid."""

    _name = "ekap.bid.line"
    _description = "Tender Bid Item"
    _order = "bid_id, id"

    bid_id = fields.Many2one("ekap.bid", required=True, ondelete="cascade", index=True)
    item_id = fields.Many2one("ekap.tender.item", required=True, ondelete="cascade", string="Work Item")
    name = fields.Char(related="item_id.name", string="Description")
    item_no = fields.Char(related="item_id.item_no", string="Item No")
    uom_id = fields.Many2one(related="item_id.uom_id", string="Unit")
    quantity = fields.Float(related="item_id.quantity", string="Quantity", store=True)
    authority_unit_price = fields.Monetary(related="item_id.authority_unit_price", string="Authority Unit Price")
    offer_unit_price = fields.Monetary(string="Offer Unit Price")
    price_subtotal = fields.Monetary(compute="_compute_subtotal", store=True, string="Amount")
    currency_id = fields.Many2one(related="bid_id.currency_id", string="Currency")
    company_id = fields.Many2one(related="bid_id.company_id", store=True, index=True)
    note = fields.Char()

    @api.depends("quantity", "offer_unit_price")
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.offer_unit_price
