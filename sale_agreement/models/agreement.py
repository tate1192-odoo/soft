from odoo import fields, models
from odoo.tools.translate import html_translate


class SaleAgreementTemplate(models.Model):
    _name = 'sale.agreement.template'
    _order = "priority desc, id desc"
    _description = 'Sale Agreement Template'

    name = fields.Char(string='Agreement Name', required=True, translate=True)
    agreement = fields.Html(string='Agreement Content', required=True, translate=html_translate)
    company_id = fields.Many2one("res.company", string="Company", required=True, default=lambda self: self.env.company)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'High'),
    ], default='0', index=True, string="Priority")
    active = fields.Boolean(default=True)
