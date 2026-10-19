from collections import defaultdict

from odoo import api, fields, models
from odoo.tools.translate import html_translate


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def _get_default_sale_terms_temp_up_id(self):
        return self.env["sale.terms.template"].search(
            [
                ('position', '=', 'up'),
                ('priority', '=', '1'),
                '|',
                ('company_id', '=', self.env.company.id),
                ('company_id', '=', False),
            ],
            limit=1,
        ).id

    @api.model
    def _get_default_sale_terms_temp_down_id(self):
        return self.env["sale.terms.template"].search(
            [
                ('position', '=', 'down'),
                ('priority', '=', '1'),
                '|',
                ('company_id', '=', self.env.company.id),
                ('company_id', '=', False),
            ],
            limit=1,
        ).id

    sale_terms_temp_up_id = fields.Many2one('sale.terms.template', string='Terms Template Up',
                                            default=_get_default_sale_terms_temp_up_id)
    sale_terms_temp_down_id = fields.Many2one('sale.terms.template', string='Terms Template Down',
                                              default=_get_default_sale_terms_temp_down_id)
    sale_terms_up = fields.Html(string='Terms Up', translate=html_translate)
    sale_terms_down = fields.Html(string='Terms Down', translate=html_translate)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._apply_terms_from_templates()
        return orders

    def _apply_terms_from_templates(self):
        """Materialise empty terms content from the linked templates.

        The defaults only link the template record; without this the content
        stays empty until someone touches the field in the form and the
        printed documents carry no terms. One write per template for the
        whole batch; content that is already set is never overwritten.
        """
        for content_field, template_field in (
            ('sale_terms_up', 'sale_terms_temp_up_id'),
            ('sale_terms_down', 'sale_terms_temp_down_id'),
        ):
            groups = defaultdict(lambda: self.browse())
            for order in self:
                if not order[content_field] and order[template_field]:
                    groups[order[template_field]] |= order
            for template, orders in groups.items():
                orders.write({content_field: template.terms})

    @api.onchange('sale_terms_temp_up_id')
    def _set_terms1(self):
        for terms in self:
            if terms.sale_terms_temp_up_id:
                terms.sale_terms_up = terms.sale_terms_temp_up_id.terms

    @api.onchange('sale_terms_temp_down_id')
    def _set_terms2(self):
        for terms in self:
            if terms.sale_terms_temp_down_id:
                terms.sale_terms_down = terms.sale_terms_temp_down_id.terms
