from odoo.tests import TransactionCase, tagged
from psycopg2 import IntegrityError


@tagged('post_install', '-at_install')
class TestPartnerRef(TransactionCase):
    """Partner code sequence and partner category behaviour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['res.partner']
        cls.category_model = cls.env['partner.category']

    def test_seed_categories_installed(self):
        """The predefined categories are available."""
        codes = ['company', 'bronze', 'silver', 'gold', 'platinum', 'diamond', 'supplier']
        categories = self.category_model.search([('code', 'in', codes)])
        self.assertEqual(set(categories.mapped('code')), set(codes))

    def test_partner_code_assigned_to_new_company(self):
        """A new company receives the next value of the res.partner sequence."""
        company = self.partner_model.create({
            'name': 'Sequence Test Company',
            'is_company': True,
        })
        self.assertTrue(company.partner_code)
        self.assertTrue(company.partner_code.startswith('P/'))

    def test_partner_code_not_consumed_by_child_contact(self):
        """Contact creation does not consume a new sequence number."""
        first = self.partner_model.create({
            'name': 'Sequence First Company',
            'is_company': True,
        })
        self.partner_model.create({
            'name': 'Sequence First Contact',
            'parent_id': first.id,
        })
        second = self.partner_model.create({
            'name': 'Sequence Second Company',
            'is_company': True,
        })
        first_number = int(first.partner_code.split('/')[-1])
        second_number = int(second.partner_code.split('/')[-1])
        self.assertEqual(second_number, first_number + 1)

    def test_partner_code_propagated_to_contact(self):
        """The code is a commercial field, so it reaches the contacts."""
        company = self.partner_model.create({
            'name': 'Sequence Parent Company',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Sequence Child Contact',
            'parent_id': company.id,
        })
        self.assertEqual(contact.partner_code, company.partner_code)

    def test_core_reference_field_untouched(self):
        """The standard Reference field is not filled by the module."""
        company = self.partner_model.create({
            'name': 'Reference Test Company',
            'is_company': True,
        })
        self.assertFalse(company.ref)
        self.assertTrue(company.partner_code)

    def test_bulk_assign_and_clear(self):
        """The assign wizard sets and removes the category on many partners."""
        category = self.category_model.search([('code', '=', 'gold')], limit=1)
        self.assertTrue(category)
        partners = self.partner_model.create([
            {'name': 'Bulk Partner A', 'is_company': True},
            {'name': 'Bulk Partner B', 'is_company': True},
        ])
        wizard = self.env['partner.category.assign'].with_context(
            active_model='res.partner',
            active_ids=partners.ids,
        ).create({
            'category_id': category.id,
        })
        self.assertEqual(wizard.partner_ids, partners)
        wizard.action_apply()
        self.assertEqual(partners.mapped('partner_category_id'), category)

        partner = partners[0]
        self.assertEqual(category.partner_count, len(category.partner_ids))
        self.assertIn(partner, category.partner_ids)

        clear_wizard = self.env['partner.category.assign'].create({
            'category_id': category.id,
            'partner_ids': [(6, 0, partners.ids)],
        })
        clear_wizard.action_clear()
        self.assertFalse(any(partners.mapped('partner_category_id')))

    def test_partner_code_resequence_wizard(self):
        """The wizard renumbers commercial partners in chronological order."""
        first = self.partner_model.create({
            'name': 'Resequence First',
            'is_company': True,
        })
        second = self.partner_model.create({
            'name': 'Resequence Second',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Resequence First Contact',
            'parent_id': first.id,
        })
        wizard = self.env['partner.code.resequence.wizard'].create({})
        self.assertGreaterEqual(wizard.total_count, 2)
        wizard.action_resequence()
        first_number = int(first.partner_code.split('/')[-1])
        self.assertEqual(
            int(second.partner_code.split('/')[-1]),
            first_number + 1,
        )
        self.assertEqual(contact.partner_code, first.partner_code)

    def test_bulk_assign_contact_uses_company(self):
        """Selecting a contact assigns the category through its company."""
        category = self.category_model.search([('code', '=', 'gold')], limit=1)
        company = self.partner_model.create({
            'name': 'Contact Assignment Company',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Contact Assignment Contact',
            'parent_id': company.id,
        })
        wizard = self.env['partner.category.assign'].with_context(
            active_model='res.partner',
            active_ids=contact.ids,
        ).create({'category_id': category.id})
        wizard.action_apply()
        self.assertEqual(company.partner_category_id, category)
        self.assertEqual(contact.partner_category_id, category)

        wizard.action_clear()
        self.assertFalse(company.partner_category_id)
        self.assertFalse(contact.partner_category_id)

    def test_contact_copy_to_standalone_gets_code(self):
        """A contact copied as a standalone partner receives a new code."""
        company = self.partner_model.create({
            'name': 'Copy Source Company',
            'is_company': True,
        })
        contact = self.partner_model.create({
            'name': 'Copy Source Contact',
            'parent_id': company.id,
        })
        copied = contact.copy({'parent_id': False})
        self.assertTrue(copied.partner_code)
        self.assertTrue(copied.partner_code.startswith('P/'))
        self.assertNotEqual(copied.partner_code, contact.partner_code)

    def test_unique_code_constraint(self):
        """Two categories cannot share the same code."""
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.category_model.create({'name': 'Diamond Bis', 'code': 'diamond'})
