from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    has_discount = fields.Boolean(
        compute='_compute_has_discount',
        store=True,
    )
    has_tax = fields.Boolean(
        compute='_compute_has_tax',
        store=True,
    )

    @api.depends('order_line.discount')
    def _compute_has_discount(self):
        for order in self:
            order.has_discount = any(
                line.discount > 0 for line in order.order_line
                if not line.display_type
            )

    @api.depends('order_line.tax_ids')
    def _compute_has_tax(self):
        for order in self:
            order.has_tax = any(
                line.tax_ids for line in order.order_line
                if not line.display_type
            )
