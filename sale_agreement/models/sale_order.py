from odoo import api, fields, models
from odoo.tools.translate import html_translate


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sale_agreement_template_id = fields.Many2one('sale.agreement.template', string='Sale Agreement Template')
    sale_agreement = fields.Html(string='Sale Agreement Line', translate=html_translate)

    def _action_confirm(self):
        """Auto-load high priority template if agreement is empty"""
        res = super()._action_confirm()

        # Seed the agreement of freshly confirmed orders that do not carry
        # one yet, from the high-priority template of the same company.
        # One lookup for the whole batch; existing content is preserved.
        orders_to_fill = self.filtered(lambda order: not order.sale_agreement)
        if orders_to_fill:
            templates = self.env["sale.agreement.template"].search([('priority', '=', '1')])
            for order in orders_to_fill:
                template = templates.filtered(
                    lambda t, company=order.company_id: t.company_id == company
                )[:1]
                if template:
                    order.sale_agreement = template.agreement
        return res

    @api.onchange('sale_agreement_template_id')
    def _onchange_sale_agreement_template_id(self):
        """Load template content when template is selected"""
        if self.sale_agreement_template_id:
            self.sale_agreement = self.sale_agreement_template_id.agreement
        else:
            self.sale_agreement = False
