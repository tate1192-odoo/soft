# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for the template value hints (models/value_hints.py).

The hints answer "what can I print for this model" and are used by the form,
the draft help box and the field-path validation on Activate.  Three sources
are covered here: an explicit model declaration, the module's own QWeb reports
(following ``t-call`` chains) and the field types.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_simple_docx,
)

WRAPPER_ARCH = '''<t t-call="web.html_container">
    <t t-foreach="docs" t-as="doc">
        <t t-call="test.hints.document"/>
    </t>
</t>'''

DOCUMENT_ARCH = '''<t t-call="web.external_layout">
    <div class="page">
        <h2 t-field="doc.name"/>
        <span t-field="doc.website"/>
        <table>
            <tr t-foreach="doc.child_ids" t-as="line">
                <td t-field="line.name"/>
                <td t-field="line.email"/>
            </tr>
        </table>
    </div>
</t>'''


@tagged('post_install', '-at_install')
class TestValueHints(SoftReportGeneratorCommon):

    def _hint_paths(self, model_name):
        template = self.env['soft.report.template']
        return template._soft_report_value_hints(model_name)

    # ------------------------------------------------------------------
    #  Source 3 — field types
    # ------------------------------------------------------------------

    def test_hints_from_field_types(self):
        hints = self._hint_paths('res.partner')
        self.assertTrue(hints, 'a model always yields at least a few hints')
        paths = [hint['path'] for hint in hints]
        self.assertIn('name', paths, 'the preferred char field comes first')
        kinds = {hint['kind'] for hint in hints}
        self.assertIn('relation', kinds, 'a many2one example is included')
        for hint in hints:
            self.assertTrue(hint['placeholder'].startswith('{{'))

    def test_hints_text_is_copyable(self):
        template = self.env['soft.report.template']
        text = template._soft_report_hints_text('res.partner')
        self.assertIn('{{name}}', text)
        self.assertIn('\n', text)

    # ------------------------------------------------------------------
    #  Source 2 — QWeb reports (t-call chain + loop children)
    # ------------------------------------------------------------------

    def _make_report(self):
        View = self.env['ir.ui.view'].sudo()
        View.create({
            'name': 'test hints wrapper',
            'type': 'qweb',
            'key': 'test.hints.wrapper',
            'arch': WRAPPER_ARCH,
        })
        View.create({
            'name': 'test hints document',
            'type': 'qweb',
            'key': 'test.hints.document',
            'arch': DOCUMENT_ARCH,
        })
        return self.env['ir.actions.report'].sudo().create({
            'name': 'Hints Test Report',
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'test.hints.wrapper',
        })

    def test_hints_follow_tcall_chain_and_loops(self):
        report = self._make_report()
        template = self.env['soft.report.template']
        hints = template._soft_report_value_hints('res.partner')
        paths = [hint['path'] for hint in hints]
        self.assertIn('website', paths,
                      'fields live in the t-call-ed document template')
        loops = {hint['path']: hint for hint in hints if hint['kind'] == 'loop'}
        self.assertIn('child_ids', loops, 'the foreach field is a loop hint')
        child_paths = [child['path'] for child in loops['child_ids']['children']]
        self.assertIn('name', child_paths)
        self.assertIn('email', child_paths)
        report.unlink()
        self.env['ir.ui.view'].sudo().search([
            ('key', 'in', ('test.hints.wrapper', 'test.hints.document')),
        ]).unlink()

    # ------------------------------------------------------------------
    #  Source 1 — declaration on the model wins
    # ------------------------------------------------------------------

    def test_model_declaration_is_used(self):
        declared = [
            {'path': 'name', 'label': 'Declared Name'},
            {'path': 'email', 'kind': 'field'},
            'website',  # plain path strings are accepted too
        ]
        with patch.object(
            type(self.env['res.partner']),
            '_soft_report_value_hints',
            lambda self: declared,
            create=True,
        ):
            hints = self._hint_paths('res.partner')
        by_path = {hint['path']: hint for hint in hints}
        self.assertEqual(by_path['name']['label'], 'Declared Name')
        self.assertIn('email', by_path)
        self.assertIn('website', by_path)

    # ------------------------------------------------------------------
    #  Field-path validation on Activate
    # ------------------------------------------------------------------

    def test_activate_accepts_loop_children_and_system_placeholders(self):
        """Loop children resolve against the loop item; tax_totals_* are not fields."""
        template = self._build_template(
            make_simple_docx('{{#child_ids}}', '{{name}}', '{{/child_ids}}',
                             'Total: {{tax_totals_total}}'),
            field_ids=[
                (0, 0, {'placeholder': 'child_ids', 'field_path': 'child_ids',
                        'is_loop': True}),
                # child path is relative to res.partner (the loop item)
                (0, 0, {'placeholder': 'name', 'field_path': 'name',
                        'loop_parent': 'child_ids'}),
                # filled from tax_totals at render time, not a model field
                (0, 0, {'placeholder': 'tax_totals_total',
                        'field_path': 'tax_totals_total',
                        'auto_resolved': True}),
            ],
            state='ready',
        )
        template.action_activate()
        self.assertEqual(template.state, 'active')

    def test_activate_rejects_unknown_field_path(self):
        template = self._build_template(
            make_simple_docx('{{nope}}'),
            field_ids=[(0, 0, {
                'placeholder': 'nope',
                'field_path': 'this_field_does_not_exist',
            })],
            state='ready',
        )
        with self.assertRaises(UserError):
            template.action_activate()

    # ------------------------------------------------------------------
    #  Activate puts the entry in the Print menu
    # ------------------------------------------------------------------

    def test_activate_binds_action_to_print_menu(self):
        template = self._build_template(
            make_simple_docx('{{name}}'),
            field_ids=[(0, 0, {'placeholder': 'name', 'field_path': 'name'})],
            state='ready',
        )
        template.action_activate()
        action = template.server_action_id
        self.assertEqual(action.binding_type, 'report',
                         'the Print menu is where users look for reports')
        self.assertEqual(action.binding_model_id.model, 'res.partner')
        self.assertEqual(
            action.group_ids,
            self.env.ref('soft_report_generator.group_soft_report_generator_user'),
        )
