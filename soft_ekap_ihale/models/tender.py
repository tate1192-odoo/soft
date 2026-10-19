from odoo import _, api, fields, models
from odoo.exceptions import UserError

TENDER_TYPES = [
    ("goods", "Goods Purchase"),
    ("works", "Construction Works"),
    ("services", "Service Procurement"),
    ("consultancy", "Consultancy"),
]

TENDER_METHODS = [
    ("open", "Open Procedure"),
    ("restricted", "Restricted Procedure"),
    ("negotiated", "Negotiated Procedure"),
    ("direct", "Direct Procurement"),
]

TENDER_STATES = [
    ("draft", "Draft"),
    ("following", "Following"),
    ("in_preparation", "Bid Preparation"),
    ("submitted", "Submitted"),
    ("won", "Won"),
    ("lost", "Lost"),
    ("cancelled", "Cancelled"),
]


class EkapTender(models.Model):
    """One public tender (tender) the company follows or bids on."""

    _name = "ekap.tender"
    _description = "Public Tender"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "bid_deadline desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, default="/", copy=False, index=True)
    tender_no = fields.Char(
        string="Tender Reference Number",
        tracking=True,
        help="Tender reference number: year/province/authority/sequence, e.g. 2026/123456.",
    )
    contracting_authority = fields.Char(string="Contracting Authority", tracking=True)
    province_id = fields.Many2one(
        "res.country.state",
        string="Province",
        domain="[('country_id.code', '=', 'TR')]",
    )
    tender_type = fields.Selection(TENDER_TYPES, string="Type", required=True, default="services", tracking=True)
    method = fields.Selection(TENDER_METHODS, string="Procedure", default="open")
    state = fields.Selection(TENDER_STATES, default="draft", required=True, tracking=True, index=True)

    announcement_date = fields.Datetime(string="Announcement Date")
    qa_date = fields.Datetime(string="Q&A Date")
    bid_deadline = fields.Datetime(
        string="Tender (Bid Deadline) Date",
        tracking=True,
        help="The last moment a bid can be given; the e-key deadline uses the same time.",
    )

    approximate_cost = fields.Monetary(string="Approximate Cost", tracking=True)
    limit_value = fields.Monetary(
        string="Limit Value",
        help="The limit value published by the authority/EKAP or computed in this module. "
        "Left empty, the abnormally low bid check is skipped.",
    )
    limit_value_source = fields.Selection(
        [
            ("not_entered", "Not entered"),
            ("contracting_authority", "Authority / EKAP announcement"),
            ("computed", "Computed in this module"),
        ],
        string="Limit Value Source",
        default="not_entered",
        required=True,
    )
    n_coefficient = fields.Float(
        string="N Coefficient",
        digits=(6, 4),
        help="Construction works limit value coefficient (KGT 45.1.1.1): 1.00 for "
        "superstructure, electrical, mechanical installation and telecommunication "
        "works and their completion/repair; 1.20 for other works. The tender documents may state another value.",
    )
    r_coefficient = fields.Float(
        string="R Coefficient",
        digits=(6, 4),
        help="Service procurement limit value coefficient (KGT 79.1.2), set yearly by a "
        "KİK decision, read from the parameter table.",
    )
    personnel_based = fields.Boolean(
        string="Personnel Based",
        help="When set, the bid cannot be below the labour minimum cost (KGT 79.7/79.5).",
    )
    partial_bid_allowed = fields.Boolean(string="Partial Bids Allowed")
    reject_without_explanation = fields.Boolean(
        string="Reject Without Explanation",
        help="Law 4734 art.38, last paragraph: for works whose approximate cost is up to "
        "half of the threshold and for some service kinds, a bid below the limit "
        "value is rejected without an explanation.",
    )

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    user_id = fields.Many2one(
        "res.users", string="Responsible", default=lambda self: self.env.user, tracking=True
    )
    item_ids = fields.One2many("ekap.tender.item", "tender_id", string="Work Items")
    bid_ids = fields.One2many("ekap.bid", "tender_id", string="Bids")
    labor_calc_id = fields.Many2one("ekap.labor.calc", string="Labour Calculation")
    document_ids = fields.Many2many(
        "ir.attachment",
        "ekap_tender_ir_attachment_rel",
        "tender_id",
        "attachment_id",
        string="Tender Documents",
    )
    item_count = fields.Integer(compute="_compute_counts", string="Item Count")
    bid_count = fields.Integer(compute="_compute_counts", string="Bid Count")
    best_bid_id = fields.Many2one("ekap.bid", compute="_compute_best_bid", string="Best Bid")
    check_message = fields.Char(compute="_compute_check", string="Bid Check")
    check_status = fields.Selection(
        [("ok", "OK"), ("warning", "Warning"), ("risk", "Risk")],
        compute="_compute_check",
        string="Check Status",
    )
    # --- Award result, filled once the tender is concluded ----------------------
    winning_firm = fields.Char(
        string="Winning Firm",
        tracking=True,
        help="The firm the contract was awarded to, as printed in the result notice "
        "(EKAP result notice). Our own company is filled in automatically when our bid wins.",
    )
    contract_price = fields.Monetary(
        string="Contract Price",
        tracking=True,
        help="The contract price of the result notice. Together with the approximate cost "
        "it gives the discount the authority actually awarded.",
    )
    valid_bid_count = fields.Integer(
        string="Valid Bids",
        help="How many valid bids the authority evaluated. One valid bid means there was "
        "no real competition — the flag procurement watchdogs look for.",
    )
    discount_rate = fields.Float(
        string="Discount (%)",
        compute="_compute_discount",
        store=True,
        digits=(6, 2),
        help="(Approximate cost − contract price) / approximate cost. It can be negative "
        "(a contract signed above the estimate). 0 means the figure could not be computed "
        "because one of the two amounts is not entered: the module does not guess, and "
        "the authority history says how many results a mean is based on.",
    )
    authority_history = fields.Char(
        string="Authority History",
        compute="_compute_authority_history",
        help="What the tenders recorded in this database say about the same authority and "
        "the same tender kind: how many results exist, their mean discount and the mean "
        "number of valid bids. It grows with every result you record.",
    )

    note = fields.Html(string="Notes")

    @api.depends("item_ids", "bid_ids")
    def _compute_counts(self):
        for tender in self:
            tender.item_count = len(tender.item_ids)
            tender.bid_count = len(tender.bid_ids)

    @api.depends("bid_ids.state", "bid_ids.bid_total")
    def _compute_best_bid(self):
        for tender in self:
            bids = tender.bid_ids.filtered(lambda b: b.state != "cancelled")
            tender.best_bid_id = bids.sorted("bid_total")[:1]

    @api.depends(
        "bid_ids.state",
        "bid_ids.bid_total",
        "bid_ids.abnormally_low",
        "bid_ids.labor_warning",
        "limit_value",
        "tender_type",
        "personnel_based",
    )
    def _compute_check(self):
        for tender in self:
            bid = tender.best_bid_id
            if not bid:
                tender.check_message = _("No bid has been created yet.")
                tender.check_status = "warning"
                continue
            messages = []
            if tender.personnel_based and bid.labor_warning:
                messages.append(bid.labor_warning)
            if bid.abnormally_low:
                messages.append(bid.abnormally_low_status)
            if not tender.limit_value and tender.tender_type in ("works", "services"):
                messages.append(_("No limit value is entered."))
            if messages:
                tender.check_message = " ".join(messages)
                tender.check_status = "risk" if bid.labor_warning else "warning"
            else:
                tender.check_message = _("The bid checks are OK.")
                tender.check_status = "ok"

    @api.depends("approximate_cost", "contract_price")
    def _compute_discount(self):
        """Discount of the award: estimate to contract price, sign kept.

        Leaving it 0 when a figure is missing is deliberate: a Float column cannot
        hold "no value", so the honest signal lives in ``_authority_history``,
        which reports how many results a mean was computed over.
        """
        for tender in self:
            if tender.approximate_cost and tender.contract_price:
                tender.discount_rate = (
                    (tender.approximate_cost - tender.contract_price)
                    / tender.approximate_cost
                    * 100.0
                )
            else:
                tender.discount_rate = 0.0

    @api.model
    def _authority_history(self, contracting_authority, tender_type=None, exclude_id=None):
        """Discount and competition of the concluded tenders of one authority.

        Returns ``considered`` (concluded tenders of that authority), ``used``
        (those whose discount could be computed, i.e. both amounts are published)
        and the two means over ``used``. A mean without its base is not a number
        anybody should bid on, so the counts travel with it.
        """
        empty = {"considered": 0, "used": 0, "mean_discount": 0.0, "mean_valid_bids": 0.0}
        if not contracting_authority:
            return empty
        domain = [("contracting_authority", "=", contracting_authority), ("state", "in", ("won", "lost"))]
        if tender_type:
            domain.append(("tender_type", "=", tender_type))
        if exclude_id:
            domain.append(("id", "!=", exclude_id))
        concluded = self.search(domain)
        used = concluded.filtered(lambda t: t.approximate_cost and t.contract_price)
        if not used:
            return dict(empty, considered=len(concluded))
        with_bids = used.filtered("valid_bid_count")
        return {
            "considered": len(concluded),
            "used": len(used),
            "mean_discount": sum(used.mapped("discount_rate")) / len(used),
            "mean_valid_bids": (sum(with_bids.mapped("valid_bid_count")) / len(with_bids)) if with_bids else 0.0,
        }

    @api.depends(
        "contracting_authority",
        "tender_type",
        "approximate_cost",
        "contract_price",
        "valid_bid_count",
    )
    def _compute_authority_history(self):
        for tender in self:
            if not tender.contracting_authority:
                tender.authority_history = _("Enter the contracting authority to see its history.")
                continue
            history = self._authority_history(tender.contracting_authority, tender.tender_type, tender.id)
            if not history["considered"]:
                tender.authority_history = _("No concluded tender of this authority is recorded yet.")
                continue
            if not history["used"]:
                tender.authority_history = _(
                    "%(considered)s recorded results, none with a published contract price.",
                    considered=history["considered"],
                )
                continue
            if history["mean_valid_bids"]:
                tender.authority_history = _(
                    "%(used)s of %(considered)s recorded results · mean discount %(discount)s · "
                    "mean %(bid)s valid bids",
                    used=history["used"],
                    considered=history["considered"],
                    discount="%.2f%%" % history["mean_discount"],
                    bid="%.1f" % history["mean_valid_bids"],
                )
            else:
                tender.authority_history = _(
                    "%(used)s of %(considered)s recorded results · mean discount %(discount)s",
                    used=history["used"],
                    considered=history["considered"],
                    discount="%.2f%%" % history["mean_discount"],
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ekap.tender") or "/"
        return super().create(vals_list)

    @api.onchange("tender_type")
    def _onchange_tender_type(self):
        """N and R only apply to their own tender kind."""
        Params = self.env["ekap.parameter"]
        if self.tender_type == "works" and not self.n_coefficient:
            self.n_coefficient = Params.get_value_or_false("WORKS_N_OTHER") or 0.0
        if self.tender_type == "services" and not self.r_coefficient:
            self.r_coefficient = Params.get_value_or_false("SERVICE_R_OTHER") or 0.0

    def action_state_following(self):
        self.write({"state": "following"})

    def action_state_in_preparation(self):
        self.write({"state": "in_preparation"})

    def action_state_cancelled(self):
        self.write({"state": "cancelled"})

    def action_open_limit_value_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Limit Value Calculation"),
            "res_model": "ekap.limit.value.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_tender_id": self.id},
        }

    def action_create_bid(self):
        """Create a draft bid for this tender (one is enough in practice)."""
        self.ensure_one()
        bid = self.env["ekap.bid"].create({"tender_id": self.id})
        bid.action_generate_lines()
        self.write({"state": "in_preparation"})
        return {
            "type": "ir.actions.act_window",
            "res_model": "ekap.bid",
            "res_id": bid.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_bids(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Bids"),
            "res_model": "ekap.bid",
            "view_mode": "list,form",
            "domain": [("tender_id", "=", self.id)],
            "context": {"default_tender_id": self.id},
        }


class EkapTenderItem(models.Model):
    """A work item (item) of the tender, i.e. one line of the price schedule."""

    _name = "ekap.tender.item"
    _description = "Tender Work Item"
    _order = "tender_id, sequence, id"

    tender_id = fields.Many2one(
        "ekap.tender", required=True, ondelete="cascade", index=True, string="Tender"
    )
    sequence = fields.Integer(default=10)
    item_no = fields.Char(string="Item No")
    name = fields.Char(string="Work Item", required=True)
    uom_id = fields.Many2one("uom.uom", string="Unit")
    okas_code = fields.Char(string="OKAS Code")
    quantity = fields.Float(
        string="Quantity", digits="Product Unit of Measure", help="The quantity stated in the tender documents."
    )
    authority_unit_price = fields.Monetary(
        string="Authority Unit Price", help="The unit price of the authority's schedule, when there is one."
    )
    offer_unit_price = fields.Monetary(string="Offer Unit Price")
    price_subtotal = fields.Monetary(compute="_compute_subtotals", store=True, string="Bid Amount")
    authority_amount = fields.Monetary(compute="_compute_subtotals", store=True, string="Authority Amount")
    analysis_id = fields.Many2one("ekap.analysis", string="Analysis")
    currency_id = fields.Many2one(related="tender_id.currency_id", string="Currency")
    company_id = fields.Many2one(related="tender_id.company_id", store=True, index=True)
    note = fields.Char()

    @api.depends("quantity", "offer_unit_price", "authority_unit_price")
    def _compute_subtotals(self):
        for item in self:
            item.price_subtotal = item.quantity * item.offer_unit_price
            item.authority_amount = item.quantity * item.authority_unit_price

    def action_open_analysis(self):
        self.ensure_one()
        if not self.analysis_id:
            raise UserError(_("No analysis is linked to this item."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "ekap.analysis",
            "res_id": self.analysis_id.id,
            "view_mode": "form",
            "target": "current",
        }
