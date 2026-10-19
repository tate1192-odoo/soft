from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'soft_partner_segment')
class TestPartnerSegment(TransactionCase):
    """Partner segment model, propagation and bulk assignment."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['res.partner']
        cls.segment_model = cls.env['partner.segment']

    def test_seed_segments_installed(self):
        """The predefined segments are available with their codes."""
        codes = [
            'key', 'regular', 'oneoff', 'passive', 'prospect',
            'lead_warm', 'lead_reachable', 'lead_address', 'vendor', 'rubbish',
        ]
        segments = self.segment_model.search([('code', 'in', codes)])
        self.assertEqual(set(segments.mapped('code')), set(codes))

    def test_segment_is_commercial_field(self):
        """The segment is propagated from the company to its contacts."""
        self.assertIn('partner_segment_id', self.partner_model._commercial_fields())
        company = self.partner_model.create({
            'name': 'Segment Parent Company',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Segment Child Contact',
            'parent_id': company.id,
        })
        segment = self.segment_model.search([('code', '=', 'key')], limit=1)
        company.partner_segment_id = segment
        self.assertEqual(contact.partner_segment_id, segment)

    def test_bulk_assign_and_clear(self):
        """The assign wizard sets and removes the segment on many partners."""
        segment = self.segment_model.search([('code', '=', 'regular')], limit=1)
        partners = self.partner_model.create([
            {'name': 'Segment Bulk A', 'is_company': True},
            {'name': 'Segment Bulk B', 'is_company': True},
        ])
        wizard = self.env['partner.segment.assign'].with_context(
            active_model='res.partner',
            active_ids=partners.ids,
        ).create({'segment_id': segment.id})
        self.assertEqual(wizard.partner_ids, partners)
        wizard.action_apply()
        self.assertEqual(partners.mapped('partner_segment_id'), segment)
        self.assertEqual(segment.partner_count, len(segment.partner_ids))

        clear_wizard = self.env['partner.segment.assign'].create({
            'segment_id': segment.id,
            'partner_ids': [(6, 0, partners.ids)],
        })
        clear_wizard.action_clear()
        self.assertFalse(any(partners.mapped('partner_segment_id')))

    def test_bulk_assign_contact_uses_company(self):
        """Selecting a contact assigns the segment through its company."""
        segment = self.segment_model.search([('code', '=', 'key')], limit=1)
        company = self.partner_model.create({
            'name': 'Segment Contact Company',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Segment Contact Contact',
            'parent_id': company.id,
        })
        wizard = self.env['partner.segment.assign'].with_context(
            active_model='res.partner',
            active_ids=contact.ids,
        ).create({'segment_id': segment.id})
        wizard.action_apply()
        self.assertEqual(company.partner_segment_id, segment)
        self.assertEqual(contact.partner_segment_id, segment)

        wizard.action_clear()
        self.assertFalse(company.partner_segment_id)
        self.assertFalse(contact.partner_segment_id)

    def test_unique_code_constraint(self):
        """Two segments cannot share the same code."""
        from psycopg2 import IntegrityError

        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.segment_model.create({'name': 'Kilit Bis', 'code': 'key'})
