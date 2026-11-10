# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Child model: maps a ``{{placeholder}}`` to a field path on the template's
record.  Stored in a one2many on :class:`soft.report.template`.
"""

from odoo import fields, models


class SoftReportTemplateField(models.Model):
    _name = 'soft.report.template.field'
    _description = 'Report Template Field Mapping'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'soft.report.template', string='Template',
        required=True, ondelete='cascade',
    )
    placeholder = fields.Char('Placeholder', required=True)
    field_path = fields.Char(
        'Field Path',
        help='Dot-separated path to a field on the model, e.g. partner_id.name',
    )
    is_loop = fields.Boolean(
        'Is Loop',
        help='Check if this placeholder marks a repeating section (One2many field).',
    )
    loop_parent = fields.Char(
        'Loop Parent',
        help='If this placeholder is inside a loop, enter the loop placeholder name.',
    )
    auto_resolved = fields.Boolean('Auto Resolved', readonly=True)
    description = fields.Char('Description')
    sequence = fields.Integer('Sequence', default=10)
