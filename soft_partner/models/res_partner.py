from odoo import api, exceptions, fields, models


class ResPartner(models.Model):

    _inherit = 'res.partner'

    # Dedicated partner code, never copied, filled from ir.sequence
    partner_code = fields.Char(
        string='Code',
        index=True,
        copy=False,
        help="Code assigned automatically from the res.partner sequence "
             "(prefix P/). Assigned to commercial partners and propagated to "
             "their contacts.",
    )
    partner_category_id = fields.Many2one(
        'partner.category',
        string='Category',
        index=True,
        tracking=True,
        ondelete='set null',
        help="Classification level of the partner, e.g. Bronze or Gold.",
    )
    partner_segment_id = fields.Many2one(
        'partner.segment',
        string='Segment',
        index=True,
        tracking=True,
        ondelete='set null',
        help="Commercial weight segment of the partner: key account, regular, "
             "one off, passive, prospect or junk. Filled from the invoice "
             "history.",
    )

    def _get_next_partner_code(self, vals=None):
        return self.env['ir.sequence'].next_by_code('res.partner')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('partner_code') and self._needs_partner_code(vals=vals):
                vals['partner_code'] = self._get_next_partner_code(vals=vals)
        return super().create(vals_list)

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        if not default.get('partner_code') and self._needs_partner_code(vals=default):
            default['partner_code'] = self._get_next_partner_code(vals=default)
        return super().copy(default)

    def write(self, vals):
        for partner in self:
            partner_vals = dict(vals)
            if (
                not partner_vals.get('partner_code')
                and partner._needs_partner_code(vals=partner_vals)
                and not partner.partner_code
            ):
                partner_vals['partner_code'] = partner._get_next_partner_code(
                    vals=partner_vals
                )
            super(ResPartner, partner).write(partner_vals)
        return True

    def _needs_partner_code(self, vals=None):
        """Return True when a sequence value must be assigned.

        :param vals: known field values of the partner object
        :return: True if a sequence value should be assigned to the partner's
            ``partner_code`` field, False otherwise
        """
        if not vals and not self:  # pragma: no cover
            raise exceptions.UserError(
                self.env._("Either field values or an id must be provided.")
            )
        # only assign a code to commercial partners
        fields_for_check = ['is_company', 'parent_id']
        # Copy original vals to prevent modifying them
        vals_for_check = dict(vals) if vals else {}
        if self:
            for field_name in fields_for_check:
                if field_name not in vals_for_check:
                    vals_for_check[field_name] = self[field_name]
        return vals_for_check.get('is_company') or not vals_for_check.get('parent_id')

    @api.model
    def _commercial_fields(self):
        """Propagate the code, category and segment to the partner's contacts."""
        return super()._commercial_fields() + [
            'partner_code',
            'partner_category_id',
            'partner_segment_id',
        ]
