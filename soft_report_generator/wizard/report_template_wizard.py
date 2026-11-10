# -*- coding: utf-8 -*-

import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SoftReportTemplateWizard(models.TransientModel):
    _name = 'soft.report.template.wizard'
    _description = 'Report Template Selection Wizard'

    res_model = fields.Char('Model', required=True, readonly=True)
    res_ids_json = fields.Char('Record IDs (JSON)', readonly=True)
    template_id = fields.Many2one(
        'soft.report.template', string='Report Template',
        required=True,
        domain="[('id', 'in', available_template_ids)]",
    )
    available_template_ids = fields.Many2many(
        'soft.report.template', string='Available Templates',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get('default_res_ids'):
            res['res_ids_json'] = json.dumps(ctx['default_res_ids'])
        if ctx.get('default_available_template_ids'):
            res['available_template_ids'] = [
                (6, 0, ctx['default_available_template_ids']),
            ]
        return res

    def action_print(self):
        """Generate the report with the selected template."""
        self.ensure_one()
        if not self.template_id:
            raise UserError(_('Please select a report template.'))
        res_ids = json.loads(self.res_ids_json or '[]')
        if not res_ids:
            raise UserError(_('No records to print.'))
        if self.template_id.model_name != self.res_model:
            raise UserError(_(
                'The selected template is designed for %(model)s records, but '
                '%(other)s records were given.',
                model=self.template_id.model_name,
                other=self.res_model,
            ))
        records = self.env[self.res_model].browse(res_ids)
        return self.template_id.generate_report(records)
