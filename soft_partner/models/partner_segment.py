from odoo import api, fields, models


class PartnerSegment(models.Model):
    """Commercial weight segment of a partner (key account, regular, ...)."""

    _name = 'partner.segment'
    _description = 'Partner Segment'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Technical code used in filters and reports, e.g. key.",
    )
    description = fields.Text(
        help="Value band behind the segment, so the rule stays documented. "
             "The seed bands are examples - edit them to match your own scale.",
    )
    sequence = fields.Integer(
        default=10,
        help="Order of the segment in lists and in the group by result.",
    )
    color = fields.Integer(
        help="Color used for the kanban cards and list decorations.",
    )
    active = fields.Boolean(default=True)
    partner_ids = fields.One2many(
        'res.partner',
        'partner_segment_id',
        string='Partners',
    )
    partner_count = fields.Integer(
        string='Partner Count',
        compute='_compute_partner_count',
    )

    _code_uniq = models.Constraint(
        'unique(code)',
        'This partner segment code already exists!',
    )

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for segment in self:
            segment.partner_count = len(segment.partner_ids)

    def action_open_partners(self):
        """Open the partner list restricted to this segment."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Partners'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('partner_segment_id', '=', self.id)],
            'context': {'default_partner_segment_id': self.id},
        }
