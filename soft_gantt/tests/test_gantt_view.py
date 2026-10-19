# Copyright 2026 - Today Softteknik (<https://www.softteknik.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Tests of the ``gantt_soft`` view type.

Two things are locked here: the view type is registered the way Odoo expects
(so ``<gantt_soft>`` is a real view, usable in an action's ``view_mode``), and
the arch is validated when the view is installed, not when a user opens the
screen. The second point is the whole reason the validation lives in Python.

Nothing here needs a business module, and that is deliberate: the type is
generic, so the tests create their views on ``res.partner`` (``create_date``
and ``write_date`` are datetimes every model carries), and one test proves the
same type is accepted on a second model. This is what keeps the module
depending on ``web`` alone: each model brings its own view through a consumer
module (``field_operation_gantt`` is the reference, see the README).
"""

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

#: A valid arch on ``res.partner``: two datetimes and an Integer colour.
VALID_ARCH = (
    '<gantt_soft date_start="create_date" date_stop="write_date" color="color"/>'
)


@tagged('post_install', '-at_install', 'soft_gantt')
class TestSoftGanttView(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env['ir.ui.view']

    def _create_view(self, arch, model='res.partner'):
        """Create a view from a raw arch, forcing the constraints to run."""
        view = self.View.create({
            'name': 'test.gantt.soft',
            'model': model,
            'arch': arch,
        })
        self.env.flush_all()
        return view

    def _assert_arch_is_refused(self, arch):
        with self.assertRaises(ValidationError):
            self._create_view(arch)

    # ------------------------------------------------------------------
    # The view type is registered
    # ------------------------------------------------------------------

    def test_view_type_is_registered(self):
        """``gantt_soft`` belongs to the view type selection."""
        selection = dict(self.View._fields['type']._description_selection(self.env))
        self.assertIn('gantt_soft', selection)

    def test_act_window_view_mode_is_registered(self):
        """An action can list ``gantt_soft`` in its ``view_mode``."""
        field = self.env['ir.actions.act_window.view']._fields['view_mode']
        selection = dict(field._description_selection(self.env))
        self.assertIn('gantt_soft', selection)

    def test_view_info_advertises_the_view(self):
        """The view switcher knows the type and its label."""
        view_info = self.View.get_view_info()
        self.assertIn('gantt_soft', view_info)
        self.assertEqual(view_info['gantt_soft']['display_name'], 'Gantt')

    def test_type_is_derived_from_the_arch_root_tag(self):
        """A ``<gantt_soft>`` arch is stored with the matching type."""
        view = self._create_view(VALID_ARCH)
        self.assertEqual(view.type, 'gantt_soft')

    def test_gantt_view_can_be_resolved_by_the_model(self):
        """The server hands the arch to the client for the gantt type."""
        view = self._create_view(VALID_ARCH)
        arch = self.env['res.partner'].get_view(view.id, 'gantt_soft')['arch']
        self.assertIn('gantt_soft', arch)

    # ------------------------------------------------------------------
    # The arch is validated at install time
    # ------------------------------------------------------------------

    def test_missing_date_start_is_refused(self):
        self._assert_arch_is_refused('<gantt_soft date_stop="write_date"/>')

    def test_missing_date_stop_is_refused(self):
        self._assert_arch_is_refused('<gantt_soft date_start="create_date"/>')

    def test_unknown_date_field_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="not_a_field"/>'
        )

    def test_non_date_field_is_refused(self):
        """A Char field cannot be used as a date."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="name" date_stop="write_date"/>'
        )

    def test_unknown_attribute_is_refused(self):
        """An attribute that is not implemented must not be silently ignored."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" whatever="1"/>'
        )

    def test_invalid_mode_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" mode="year"/>'
        )

    def test_non_numeric_limit_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" limit="many"/>'
        )

    def test_zero_limit_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" limit="0"/>'
        )

    def test_invalid_scale_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'scales="day,decade"/>'
        )

    def test_mode_outside_the_scales_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'scales="week,month" mode="day"/>'
        )

    def test_char_color_is_refused(self):
        """The palette is indexed by the Odoo colour integer, not by a text."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" color="name"/>'
        )

    def test_unsupported_group_by_field_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="write_date"/>'
        )

    def test_unknown_child_tag_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<filter name="mine"/></gantt_soft>'
        )

    def test_unsupported_declared_field_is_refused(self):
        """A relational list has no readable value to put in the card."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<field name="category_id"/></gantt_soft>'
        )

    def test_optional_attributes_are_accepted(self):
        """The optional arch attributes pass validation."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'progress="partner_latitude" color="color" mode="week" '
            'scales="day,week" limit="50" default_order="create_date asc" '
            'create="1" edit="1"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_declared_fields_are_accepted(self):
        """A renderable ``<field>`` node is what the card reads."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<field name="name"/><field name="active"/><field name="country_id"/>'
            '</gantt_soft>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_other_models_can_reuse_the_view_type(self):
        """The type is generic: any model with two date fields works."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date"/>',
            model='res.company',
        )
        self.assertEqual(view.type, 'gantt_soft')
        self.assertEqual(view.model, 'res.company')

    # ------------------------------------------------------------------
    # The module is a view type, not a business module
    # ------------------------------------------------------------------

    def test_only_web_is_a_dependency(self):
        """No business model may pull the view type in, or be pulled by it.

        A ``project`` / ``mrp`` dependency would make the type unavailable to
        every other model and tie it to the first model that used it. The
        model specific view and field belong to a consumer module instead.
        """
        module = self.env['ir.module.module'].search([('name', '=', 'soft_gantt')])
        self.assertTrue(module, "soft_gantt must be known to ir.module.module")
        self.assertEqual(module.dependencies_id.mapped('name'), ['web'])

    def test_the_enterprise_gantt_is_excluded(self):
        """``web_gantt`` and this module must never be installed together."""
        module = self.env['ir.module.module'].search([('name', '=', 'soft_gantt')])
        self.assertIn('web_gantt', module.exclusion_ids.mapped('name'))


@tagged('post_install', '-at_install', 'soft_gantt')
class TestSoftGanttViewRights(TransactionCase):
    """The arch of a gantt_soft view follows the rights of the user.

    Nothing here is specific to this module: ``ir.ui.view`` writes ``create``,
    ``delete`` and ``edit`` to ``False`` on the arch when the user lacks the
    matching right on the model (base's generic post-processing). A view type
    benefits from it simply by accepting those attributes in its arch, so a
    view type that dropped them from its whitelist would lose the protection
    without any other test noticing. This pins the behaviour for
    ``gantt_soft``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.ref('base.main_company')
        cls.env['ir.ui.view'].create({
            'name': 'test.gantt.soft.rights',
            'model': 'res.company',
            'arch': (
                '<gantt_soft date_start="create_date" date_stop="write_date" '
                'string="Companies"/>'
            ),
        })
        # base gives base.group_user read only on res.company, and
        # group_erp_manager the whole CRUD: the two roles make the assertion
        # deterministic without relying on demo data.
        cls.limited_user = cls.env['res.users'].create({
            'login': 'soft_gantt_limited',
            'name': 'Gantt limited user',
            'company_id': company.id,
            'company_ids': [(6, 0, company.ids)],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.manager_user = cls.env['res.users'].create({
            'login': 'soft_gantt_manager',
            'name': 'Gantt manager',
            'company_id': company.id,
            'company_ids': [(6, 0, company.ids)],
            'group_ids': [(6, 0, [cls.env.ref('base.group_erp_manager').id])],
        })

    def _gantt_arch(self, user):
        view = self.env['res.company'].with_user(user).get_view(False, 'gantt_soft')
        return etree.fromstring(view['arch'])

    def test_arch_reflects_the_rights_of_the_user(self):
        limited = self._gantt_arch(self.limited_user)
        self.assertEqual(limited.get('create'), 'False')
        self.assertEqual(limited.get('delete'), 'False')
        self.assertEqual(limited.get('edit'), 'False')

        allowed = self._gantt_arch(self.manager_user)
        self.assertIsNone(allowed.get('create'))
        self.assertIsNone(allowed.get('delete'))
        self.assertIsNone(allowed.get('edit'))
