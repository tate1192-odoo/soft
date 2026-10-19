from odoo import api, fields, models
from odoo.tools.translate import html_translate


class SaleTermsTemplate(models.Model):
    _name = 'sale.terms.template'
    _order = "priority desc, id desc"
    _description = 'Sale Terms Template'

    name = fields.Char(string='Terms Name', required=True, translate=True)
    terms = fields.Html(string='Terms Content', required=True, translate=html_translate)
    position = fields.Selection([('up', 'Up Line'), ('down', 'Down Line')], 'Position',)
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.company)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'High'),
    ], default='0', index=True, string="Priority")
    active = fields.Boolean(default=True)

    @api.model
    def _fix_sale_terms_default_priority(self):
        """Give the shipped down-line template the high priority on upgrade.

        The data record is ``noupdate``, so adding the priority to the XML only
        affects new databases. Existing installations get the same fix here,
        unless they already have another high-priority down-line template.
        """
        template = self.env.ref(
            'sale_terms.sale_terms_template_1', raise_if_not_found=False
        )
        if not template or template.priority == '1':
            return
        another = self.search(
            [('position', '=', 'down'), ('priority', '=', '1')], limit=1
        )
        if not another:
            template.priority = '1'

    @api.model
    def _sale_terms_remove_portal_views(self):
        """Remove the customer-portal terms views — the feature was dropped.

        Idempotent: called from a <function> tag on every install and every
        ``-u``; a no-op once the records are gone. Removing the templates
        from the data files alone does NOT delete the records that earlier
        versions already loaded into live databases.
        """
        for xmlid in ('sale_terms.portal_my_sale_term',
                      'sale_terms.portal_my_sale_term_content'):
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if view:
                view.unlink()
