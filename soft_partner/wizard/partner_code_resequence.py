from odoo import api, fields, models


class PartnerCodeResequenceWizard(models.TransientModel):
    """Resequence partner codes to fix incorrect or missing entries."""

    _name = 'partner.code.resequence.wizard'
    _description = 'Resequence Partner Codes'

    total_count = fields.Integer(string='Records to Process', readonly=True)

    @api.model
    def _resequence_domain(self):
        """Only commercial partners hold their own code.

        Contacts inherit the code of their company (commercial field), so they
        are updated by the propagation and are not resequenced themselves.
        """
        return ['|', ('is_company', '=', True), ('parent_id', '=', False)]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['total_count'] = self.env['res.partner'].search_count(
            self._resequence_domain()
        )
        return res

    def action_resequence(self):
        partners = self.env['res.partner'].search(
            self._resequence_domain(),
            order='create_date asc, id asc',
        )
        sequence = self.env['ir.sequence']
        for partner in partners:
            partner.write({
                'partner_code': sequence.next_by_code('res.partner'),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._('Partner Code'),
                'message': self.env._(
                    "%(count)s partner(s) resequenced.",
                    count=len(partners),
                ),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }
