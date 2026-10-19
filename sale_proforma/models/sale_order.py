from odoo import api, fields, models
from odoo.tools.translate import html_translate


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sale_proforma_template_id = fields.Many2one('sale.proforma.template', string='Proforma Invoice')
    sale_proforma = fields.Html(string='Proforma invoice', translate=html_translate)

    def _get_proforma_template(self, company):
        """Return the high-priority template for the order's company.

        A company-specific template wins; a template without company is the
        global fallback. Archived templates are excluded by the ORM.
        """
        return self.env["sale.proforma.template"].search(
            [
                ('priority', '=', '1'),
                '|',
                ('company_id', '=', company.id),
                ('company_id', '=', False),
            ],
            limit=1,
        )

    def action_confirm(self):
        res = super().action_confirm()
        # Seed the proforma of freshly confirmed orders that do not carry one
        # yet. Existing content is always preserved. Templates are looked up
        # per company so a multi-company batch cannot leak another company's
        # default.
        orders_to_fill = self.filtered(lambda order: not order.sale_proforma)
        templates = {}
        for order in orders_to_fill:
            company = order.company_id
            if company.id not in templates:
                templates[company.id] = self._get_proforma_template(company)
            template = templates[company.id]
            if template:
                order.sale_proforma = template.proforma
        return res

    @api.onchange('sale_proforma_template_id')
    def _set_proformas(self):
        for order in self:
            template = order.sale_proforma_template_id
            if template:
                order.sale_proforma = template.proforma
