# Copyright 2026 - Today Softteknik (<https://www.softteknik.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Tests of the ``gantt_soft`` view type.

Two things are locked here: the view type is registered the way Odoo expects
(so ``<gantt_soft>`` is a real view, usable in an action's ``view_mode``), and
the arch is validated when the view is installed, not when a user opens the
screen. The second point is the whole reason the validation lives in Python.
"""

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

VALID_ARCH = '<gantt_soft date_start="date_start" date_stop="date_deadline" color="color"/>'


@tagged('post_install', '-at_install', 'soft_gantt')
class TestSoftGanttView(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env['ir.ui.view']

    def _create_view(self, arch, model='project.task'):
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

    # ------------------------------------------------------------------
    # The arch is validated at install time
    # ------------------------------------------------------------------

    def test_missing_date_start_is_refused(self):
        self._assert_arch_is_refused('<gantt_soft date_stop="date_deadline"/>')

    def test_missing_date_stop_is_refused(self):
        self._assert_arch_is_refused('<gantt_soft date_start="date_start"/>')

    def test_unknown_date_field_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="not_a_field"/>'
        )

    def test_non_date_field_is_refused(self):
        """A Char field cannot be used as a date."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="name" date_stop="date_deadline"/>'
        )

    def test_unknown_attribute_is_refused(self):
        """An attribute that is not implemented must not be silently ignored."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" whatever="1"/>'
        )

    def test_invalid_mode_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" mode="year"/>'
        )

    def test_non_numeric_limit_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" limit="many"/>'
        )

    def test_zero_limit_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" limit="0"/>'
        )

    def test_invalid_scale_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" '
            'scales="day,decade"/>'
        )

    def test_mode_outside_the_scales_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" '
            'scales="week,month" mode="day"/>'
        )

    def test_char_color_is_refused(self):
        """The palette is indexed by the Odoo colour integer, not by a text."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" color="name"/>'
        )

    def test_unsupported_group_by_field_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" '
            'group_by="date_deadline"/>'
        )

    def test_unknown_child_tag_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline">'
            '<filter name="mine"/></gantt_soft>'
        )

    def test_unsupported_declared_field_is_refused(self):
        """A relational list has no readable value to put in the card."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="date_start" date_stop="date_deadline">'
            '<field name="user_ids"/></gantt_soft>'
        )

    def test_optional_attributes_are_accepted(self):
        """The optional arch attributes pass validation."""
        view = self._create_view(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" '
            'progress="sequence" color="color" mode="week" scales="day,week" '
            'limit="50" default_order="date_start asc" create="1" edit="1"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_other_models_can_reuse_the_view_type(self):
        """The type is generic: any model with two date fields works."""
        view = self._create_view(
            '<gantt_soft date_start="date_start" date_stop="date"/>',
            model='project.project',
        )
        self.assertEqual(view.type, 'gantt_soft')
        self.assertEqual(view.model, 'project.project')

    # ------------------------------------------------------------------
    # What the module ships
    # ------------------------------------------------------------------

    def test_shipped_task_view_is_a_gantt(self):
        view = self.env.ref('soft_gantt.view_project_task_gantt_soft')
        self.assertEqual(view.model, 'project.task')
        self.assertEqual(view.type, 'gantt_soft')
        arch = etree.fromstring(view.arch)
        self.assertEqual(arch.tag, 'gantt_soft')
        self.assertEqual(arch.get('date_start'), 'date_start')
        self.assertEqual(arch.get('date_stop'), 'date_deadline')

    def test_task_actions_offer_the_view(self):
        """Every task screen a user reaches offers the Gantt."""
        for xmlid in (
            'project.action_view_task',
            'project.action_view_my_task',
            'project.action_view_all_task',
            'project.act_project_project_2_project_task_all',
        ):
            action = self.env.ref(xmlid)
            self.assertIn('gantt_soft', action.view_mode.split(','), xmlid)

    def test_task_actions_keep_their_landing_view(self):
        """The Gantt is offered without becoming the landing view.

        This is the trap the module avoids: ``_compute_views`` builds the
        ordered view list the client receives as "the action's view records
        first, then the ``view_mode`` entries they do not cover", so binding
        the Gantt with a single ``ir.actions.act_window.view`` would silently
        make it the first view of those screens.
        """
        for xmlid in (
            'project.action_view_task',
            'project.action_view_my_task',
            'project.action_view_all_task',
            'project.act_project_project_2_project_task_all',
        ):
            action = self.env.ref(xmlid)
            modes = [mode for _view_id, mode in action.views]
            self.assertIn('gantt_soft', modes, xmlid)
            self.assertEqual(modes[0], action.view_mode.split(',')[0], xmlid)
            self.assertNotEqual(modes[0], 'gantt_soft', xmlid)

    def test_gantt_view_can_be_resolved_by_the_model(self):
        """The server hands the arch to the client for the gantt type."""
        view = self.env.ref('soft_gantt.view_project_task_gantt_soft')
        arch = self.env['project.task'].get_view(view.id, 'gantt_soft')['arch']
        self.assertIn('gantt_soft', arch)

    def test_task_start_date_field_is_added(self):
        field = self.env['project.task']._fields.get('date_start')
        self.assertTrue(field, "project.task.date_start should be added by the module")
        self.assertEqual(field.type, 'datetime')

    def test_task_form_inheritance_is_in_place(self):
        """The form patch resolved when it was created, otherwise it would not exist."""
        view = self.env.ref('soft_gantt.view_task_form2_soft_gantt')
        self.assertEqual(view.inherit_id, self.env.ref('project.view_task_form2'))
        self.assertEqual(view.type, 'form')

    def test_task_form_shows_the_start_date(self):
        form_view = self.env.ref('project.view_task_form2')
        arch = self.env['project.task'].get_view(form_view.id, 'form')['arch']
        self.assertIn('date_start', arch)


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
