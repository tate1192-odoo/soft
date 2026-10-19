from odoo import fields, models
from odoo.tools.translate import html_translate


class SaleProformaTemplate(models.Model):
    _name = 'sale.proforma.template'
    _description = 'Sale Proforma Template'

    name = fields.Char(string='Proforma Name', required=True, translate=True)
    proforma = fields.Html(string='Proforma Content', required=True, translate=html_translate)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'High'),
    ], default='0', index=True, string="Priority")
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)
