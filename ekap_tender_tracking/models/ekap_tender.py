from odoo import api, fields, models
from odoo.exceptions import ValidationError

LOSS_REASONS = [
    ("price", "Lost on Price"),
    ("technical", "Technical Score"),
    ("document", "Document / Qualification"),
    ("disqualified", "Disqualified"),
    ("cancelled", "Tender Cancelled"),
    ("other", "Other"),
]


class EkapTender(models.Model):
    """Outcome and learning fields for a followed EKAP tender."""

    _inherit = "ekap.tender"

    our_rank = fields.Integer(
        string="Our Rank",
        help="Rank of our best bid in the result notice; 0 means unknown/not ranked.",
    )
    winning_bid_amount = fields.Monetary(
        string="Winning Bid",
        help="The winner's bid amount from the result notice. Contract price can differ "
        "because of variations or corrections.",
    )
    result_date = fields.Date(string="Result Date")
    loss_reason = fields.Selection(
        LOSS_REASONS,
        string="Loss Reason",
        help="Why this tender was lost; used to group the learning history.",
    )
    price_gap = fields.Monetary(
        string="Gap to Winning Bid",
        compute="_compute_price_gap",
        store=True,
        help="Winning bid minus our best bid. Positive means our offer was lower than "
        "the winner's; negative means our offer was higher.",
    )
    price_gap_percent = fields.Float(
        string="Gap to Winning Bid (%)",
        compute="_compute_price_gap",
        store=True,
        digits=(6, 2),
    )
    next_bid_note = fields.Text(
        string="Notes for the Next Bid",
        help="What to change in the next bid: price level, cost item, documents, "
        "qualification or technical approach.",
    )

    @api.depends("winning_bid_amount", "bid_ids.bid_total", "bid_ids.state")
    def _compute_price_gap(self):
        for tender in self:
            bid = tender.bid_ids.filtered(
                lambda candidate: candidate.state != "cancelled"
            ).sorted("bid_total")[:1]
            if tender.winning_bid_amount and bid:
                gap = tender.winning_bid_amount - bid.bid_total
                tender.price_gap = gap
                tender.price_gap_percent = gap / tender.winning_bid_amount * 100.0
            else:
                tender.price_gap = 0.0
                tender.price_gap_percent = 0.0

    @api.constrains("our_rank")
    def _check_our_rank(self):
        for tender in self:
            if tender.our_rank < 0:
                raise ValidationError("Our rank cannot be negative.")

    @api.constrains("winning_bid_amount")
    def _check_winning_bid_amount(self):
        for tender in self:
            if tender.winning_bid_amount < 0:
                raise ValidationError("The winning bid cannot be negative.")
