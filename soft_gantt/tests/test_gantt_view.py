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

from types import SimpleNamespace

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

    def _validate_gantt_root(self, arch, extra_fields=None):
        """Run the ``<gantt_soft>`` validator on a field set with extras.

        The base models carry no non-stored, non-searchable date field, so the
        field set is built for the check: the validator reads a field's ``type``,
        ``store`` and ``search`` only, which a field description provides.
        """
        fields = dict(self.env['res.partner']._fields)
        fields.update(extra_fields or {})
        model = SimpleNamespace(_name='res.partner', _fields=fields)
        self.View._validate_tag_gantt_soft(
            etree.fromstring(arch), SimpleNamespace(model=model), {'validate': True}
        )

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

    def test_non_searchable_date_field_is_refused(self):
        """The window is read with a domain, so the date must be filterable.

        A computed date without a search method would install and then fail when
        the view is opened. No field of the base models is a non-stored,
        non-searchable date, so a field description is injected into the field
        set for the check.
        """
        fake = SimpleNamespace(type='datetime', store=False, search=False)
        for arch in (
            '<gantt_soft date_start="x_gantt_date" date_stop="write_date"/>',
            '<gantt_soft date_start="create_date" date_stop="x_gantt_date"/>',
        ):
            # The tag validator raises a view error (`ValueError`); the view
            # machinery turns it into the `ValidationError` of a refused view.
            with self.assertRaises(ValueError):
                self._validate_gantt_root(arch, {'x_gantt_date': fake})

    def test_searchable_non_stored_date_field_is_accepted(self):
        """A computed date with a search method is filterable: it is accepted."""
        fake = SimpleNamespace(
            type='datetime', store=False, search='_search_x_gantt_date'
        )
        self._validate_gantt_root(
            '<gantt_soft date_start="create_date" date_stop="x_gantt_date"/>',
            {'x_gantt_date': fake},
        )

    def test_unknown_attribute_is_refused(self):
        """An attribute that is not implemented must not be silently ignored."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" whatever="1"/>'
        )

    def test_invalid_mode_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" mode="decade"/>'
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
    # Milestones, dependencies and the wider scales
    # ------------------------------------------------------------------

    def test_milestone_field_is_accepted(self):
        """A boolean field may mark a record as a milestone."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'milestone="is_company"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_non_boolean_milestone_is_refused(self):
        """A milestone is a flag: a name is not one."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'milestone="name"/>'
        )

    def test_dependencies_field_is_accepted(self):
        """A one2many pointing back at the model joins two of its bars."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'dependencies="child_ids"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_dependencies_on_another_model_are_refused(self):
        """An arrow can only join two bars of the same view."""
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'dependencies="category_id"/>'
        )

    def test_non_relational_dependencies_are_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'dependencies="name"/>'
        )

    def test_quarter_and_year_are_offered_as_scales(self):
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'scales="day,week,month,quarter,year" mode="quarter" '
            'default_range="year"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')


    # ------------------------------------------------------------------
    # Decorations, group summaries, avatars and grid creation
    # ------------------------------------------------------------------

    def test_decorations_are_accepted_on_the_root_node(self):
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'decoration-danger="is_company" decoration-success="name == \'Acme\'"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_an_unknown_decoration_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'decoration-whatever="true"/>'
        )

    def test_an_empty_decoration_expression_is_refused(self):
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'decoration-danger=""/>'
        )

    def test_a_decoration_reading_an_unknown_field_is_refused(self):
        # Base's generic decoration processing resolves the identifiers and
        # refuses a field the model does not have, like a list view would.
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'decoration-danger="not_a_field == 1"/>'
        )

    def test_group_total_must_be_numeric(self):
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id" group_total="color"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id" group_total="name"/>'
        )

    def test_group_by_accepts_several_levels(self):
        """``group_by`` is a comma separated list of grouping levels."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id,color" group_total="color"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_group_by_refuses_an_invalid_level(self):
        for arch in (
            # The second level does not exist.
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id,not_a_field"/>',
            # The second level is a date: a date is the timeline, not a row.
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id,create_date"/>',
            # An empty list names no level.
            '<gantt_soft date_start="create_date" date_stop="write_date" group_by=","/>',
        ):
            self._assert_arch_is_refused(arch)

    def test_group_avatar_requires_a_many2one_group_with_an_image_field(self):
        # ``res.partner.image_1920`` is the image field, ``parent_id`` a
        # many2one to another partner.
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="parent_id" group_avatar="image_1920"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')
        for arch in (
            # The field exists on the group's model but is not binary.
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="parent_id" group_avatar="name"/>',
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="parent_id" group_avatar="no_such_field"/>',
            # No group row to draw it on.
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_avatar="image_1920"/>',
            # The group is not a many2one.
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="color" group_avatar="image_1920"/>',
        ):
            self._assert_arch_is_refused(arch)

    def test_collapse_first_level_and_cell_create_are_booleans(self):
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'group_by="company_id" collapse_first_level="1" cell_create="1"/>'
        )
        self.assertEqual(view.type, 'gantt_soft')
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'cell_create="sometimes"/>'
        )
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'collapse_first_level="maybe"/>'
        )
        # `str2bool` would accept these as false while the client reads them as
        # true: only the values both sides read the same way are accepted.
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'cell_create="off"/>'
        )
        self._assert_arch_is_refused(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            'collapse_first_level="no"/>'
        )

    # ------------------------------------------------------------------
    # Cell precision
    # ------------------------------------------------------------------

    def test_precision_is_accepted(self):
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date" '
            "precision=\"{'day': 'hour:quarter', 'week': 'day:half'}\"/>"
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_precision_is_validated(self):
        for precision in (
            # The day scale is read in hours, not in days.
            "{'day': 'day:half'}",
            # Only full, half and quarter subdivisions exist.
            "{'day': 'hour:eighth'}",
            # A week is a quarter scale's cell: it cannot be subdivided.
            "{'quarter': 'week:half'}",
            # Not a scale of this view type.
            "{'fortnight': 'day:half'}",
            # Not a dict at all.
            "'day'",
        ):
            self._assert_arch_is_refused(
                '<gantt_soft date_start="create_date" date_stop="write_date" '
                'precision="%s"/>' % precision
            )

    # ------------------------------------------------------------------
    # Actions of the details card
    # ------------------------------------------------------------------

    def test_card_buttons_are_accepted(self):
        """A view may offer actions on the record from the details card."""
        view = self._create_view(
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<field name="name"/>'
            '<button name="toggle_active" type="object" string="Archive" icon="fa fa-archive"/>'
            '<button name="base.action_partner_form" type="action" string="Open"/>'
            '<button name="toggle_active" type="object" icon="fa fa-check" confirm="Are you sure?" class="btn-danger"/>'
            '</gantt_soft>'
        )
        self.assertEqual(view.type, 'gantt_soft')

    def test_card_button_is_validated(self):
        for arch in (
            # No method / action named.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button type="object" string="Archive"/></gantt_soft>',
            # Not a supported type.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button name="toggle_active" type="method" string="Archive"/></gantt_soft>',
            # A method the model does not have.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button name="not_a_method" type="object" string="Archive"/></gantt_soft>',
            # Private methods are not actions.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button name="_compute_display_name" type="object" string="Archive"/></gantt_soft>',
            # Nothing would be drawn on the button.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button name="toggle_active" type="object"/></gantt_soft>',
            # An attribute that is not a button attribute.
            '<gantt_soft date_start="create_date" date_stop="write_date">'
            '<button name="toggle_active" type="object" string="Archive" groups="base.group_user"/>'
            '</gantt_soft>',
        ):
            self._assert_arch_is_refused(arch)

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

    def test_the_enterprise_gantt_is_not_excluded(self):
        """This module must be installable next to the Enterprise Gantt.

        ``web_gantt`` answers the ``gantt`` view type, this module the
        ``gantt_soft`` one: two different types coexist in one database. The
        Enterprise module is ``auto_install``, so an exclusion would make this
        module impossible to install on every Enterprise database.
        """
        module = self.env['ir.module.module'].search([('name', '=', 'soft_gantt')])
        self.assertNotIn('web_gantt', module.exclusion_ids.mapped('name'))
        # The two types are distinct: the consumer lists the one it wants.
        self.assertIn(
            'gantt_soft', dict(self.View._fields['type']._description_selection(self.env))
        )


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
