from odoo import api, fields, models


class PartnerSegmentAssign(models.TransientModel):
    """Assign (or remove) a partner segment on several partners at once."""

    _name = 'partner.segment.assign'
    _description = 'Assign Partner Segment'

    segment_id = fields.Many2one(
        'partner.segment',
        string='Partner Segment',
        required=True,
        help="Segment that will be set on every selected partner.",
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string='Partners',
        required=True,
        default=lambda self: self._default_partner_ids(),
    )

    @api.model
    def _default_partner_ids(self):
        active_ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') != 'res.partner':
            return []
        return [(6, 0, active_ids)]

    def _notify_result(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._('Partner Segment'),
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _commercial_partners(self):
        """Assign through the company when contacts are selected."""
        self.ensure_one()
        return self.partner_ids.commercial_partner_id

    def action_apply(self):
        self.ensure_one()
        partners = self._commercial_partners()
        partners.write({'partner_segment_id': self.segment_id.id})
        return self._notify_result(
            self.env._(
                "%(count)s partner(s) assigned to segment '%(segment)s'.",
                count=len(partners),
                segment=self.segment_id.display_name,
            )
        )

    def action_clear(self):
        self.ensure_one()
        partners = self._commercial_partners()
        partners.write({'partner_segment_id': False})
        return self._notify_result(
            self.env._(
                "Segment removed from %(count)s partner(s).",
                count=len(partners),
            )
        )
