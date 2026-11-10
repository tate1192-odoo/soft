# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for placeholder parsing, taxonomy & auto-resolution.

Covers the placeholder detection engine (``_parse_docx_placeholders``)
and auto-resolution of paths against the model.
"""

import base64

from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_docx_with_table,
    make_simple_docx,
    make_minimal_docx,
)


@tagged('post_install', '-at_install')
class TestParsePlaceholders(SoftReportGeneratorCommon):
    """Verify placeholder detection and field auto-resolution."""

    def test_parse_simple_placeholder(self):
        docx = make_simple_docx('Hello {{name}}!')
        template = self._build_template(docx)
        template.action_parse_template()
        placeholders = template.field_ids.mapped('placeholder')
        self.assertIn('name', placeholders)

    def test_parse_loop_and_children(self):
        # Table with loop markers
        body = (
            '<w:p><w:r><w:t>Top: {{ref}}</w:t></w:r></w:p>'
            + make_docx_with_table.__globals__['_make_table'](
                [
                    ['{{#order_line}}'],
                    ['{{product_id.name}}', '{{product_uom_qty}}'],
                    ['{{/order_line}}'],
                ]
            )
        )
        docx = make_minimal_docx(body)
        template = self._build_template(
            docx, model_ref='base.model_res_partner',
        )
        template.action_parse_template()
        loops = template.field_ids.filtered('is_loop').mapped('placeholder')
        self.assertIn('order_line', loops)
        children = template.field_ids.filtered(
            lambda f: f.loop_parent == 'order_line' and not f.is_loop,
        ).mapped('placeholder')
        self.assertIn('product_id.name', children)

    def test_auto_resolve_direct_field(self):
        docx = make_simple_docx('Name: {{name}}')
        template = self._build_template(docx)
        template.action_parse_template()
        name_field = template.field_ids.filtered(
            lambda f: f.placeholder == 'name',
        )
        self.assertEqual(name_field.field_path, 'name')
        self.assertTrue(name_field.auto_resolved)

    def test_auto_resolve_related_field(self):
        docx = make_simple_docx('Country: {{country_id.name}}')
        template = self._build_template(docx)
        template.action_parse_template()
        country_field = template.field_ids.filtered(
            lambda f: f.placeholder == 'country_id.name',
        )
        self.assertEqual(country_field.field_path, 'country_id.name')
        self.assertTrue(country_field.auto_resolved)

    def test_auto_resolve_unknown_field(self):
        docx = make_simple_docx('X: {{xyz_unknown}}')
        template = self._build_template(docx)
        template.action_parse_template()
        unk = template.field_ids.filtered(
            lambda f: f.placeholder == 'xyz_unknown',
        )
        self.assertFalse(unk.auto_resolved)
        self.assertFalse(unk.field_path)

    def test_expressions_not_in_field_ids(self):
        # {{=expr}} is resolved at render time, no mapping needed
        docx = make_simple_docx('Total: {{=amount_untaxed * 2}}')
        template = self._build_template(docx)
        template.action_parse_template()
        # No field mapping for expression
        self.assertFalse(
            template.field_ids.filtered(
                lambda f: '=' in f.placeholder,
            ),
        )

    def test_image_marker_not_in_field_ids(self):
        docx = make_simple_docx('Logo: {{img:self}}')
        template = self._build_template(docx)
        template.action_parse_template()
        # img: prefix is filtered out
        placeholders = template.field_ids.mapped('placeholder')
        self.assertNotIn('img:self', placeholders)


@tagged('post_install', '-at_install')
class TestGenerateReport(SoftReportGeneratorCommon):
    """Verify report generation pipeline end-to-end (without LibreOffice)."""

    def test_generate_report_single_record_original(self):
        docx = make_simple_docx('Hello {{name}}')
        template = self._build_template(
            docx, state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name',
                'field_path': 'name',
                'is_loop': False,
            })],
            template_filename='test.docx',
        )
        partner = self._make_partner('Acme')
        # Use original format to skip LibreOffice conversion
        template.write({'output_format': 'original'})
        action = template.generate_report(partner)
        self.assertEqual(action['type'], 'ir.actions.act_url')
        # Attachment is created and reachable
        url = action['url']
        self.assertIn('/web/content/', url)

    def test_generate_report_no_records_raises(self):
        docx = make_simple_docx('Hi')
        template = self._build_template(docx)
        with self.assertRaises(UserError):
            template.generate_report(self.env['res.partner'].browse())

    def test_generate_report_with_cover(self):
        docx = make_simple_docx('Body: {{name}}')
        cover = make_simple_docx('Cover: {{name}}')
        template = self._build_template(
            docx, state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name',
                'field_path': 'name',
                'is_loop': False,
            })],
            template_filename='test.docx',
        )
        template.write({
            'output_format': 'pdf',  # cover only supported for pdf
            'cover_file': base64.b64encode(cover),
            'cover_filename': 'cover.docx',
        })
        partner = self._make_partner('CoverCo')
        # Won't actually run LibreOffice, but we want to ensure the code
        # path at least doesn't crash BEFORE the conversion call.
        # Patch _convert_format to return dummy bytes.
        from unittest.mock import patch
        with patch.object(type(template), '_convert_format',
                          return_value=b'%PDF-1.4\nfake'):
            with patch.object(type(template), '_merge_pdfs',
                              return_value=b'%PDF-1.4\nmerged'):
                action = template.generate_report(partner)
                self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_write_same_file_keeps_mappings(self):
        """BUG-4: writing the same template_file must not wipe mappings."""
        docx = make_simple_docx('Hi {{name}}')
        template = self._build_template(
            docx, state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name',
                'field_path': 'name',
                'is_loop': False,
            })],
        )
        original_mapping = template.field_ids[0]
        template.write({'template_file': template.template_file})
        self.assertTrue(template.field_ids)
        self.assertEqual(template.field_ids[0].id, original_mapping.id)

    def test_write_different_file_resets_mappings(self):
        docx = make_simple_docx('Hi {{name}}')
        template = self._build_template(
            docx, state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name',
                'field_path': 'name',
                'is_loop': False,
            })],
        )
        new_docx = make_simple_docx('Different {{display_name}}')
        template.write({
            'template_file': base64.b64encode(new_docx),
        })
        self.assertFalse(template.field_ids)
        self.assertEqual(template.state, 'draft')

    def test_write_different_file_deactivates(self):
        """Active template re-uploading template resets state to draft."""
        docx = make_simple_docx('Hi {{name}}')
        template = self._build_template(
            docx, state='active',
            field_ids=[(0, 0, {
                'placeholder': 'name',
                'field_path': 'name',
                'is_loop': False,
            })],
        )
        # Bypass normal activate flow: just set state
        new_docx = make_simple_docx('Changed')
        template.write({
            'template_file': base64.b64encode(new_docx),
        })
        self.assertEqual(template.state, 'draft')

    def test_loop_field_path_must_be_one2many(self):
        """BUG-10: activating with a non-O2M loop field must raise."""
        docx = make_simple_docx('Hi')
        template = self._build_template(docx, state='ready')
        # Inject a loop mapping on `name` (Char, NOT One2many) — must fail
        self.Field.create({
            'template_id': template.id,
            'placeholder': 'name',
            'field_path': 'name',
            'is_loop': True,
        })
        with self.assertRaises(UserError):
            template.action_activate()

    def test_loop_field_path_one2many_passes(self):
        """A loop mapping on a real O2M field passes validation."""
        docx = make_simple_docx('Hi')
        template = self._build_template(docx, state='ready')
        # res.partner.child_ids is a real One2many
        self.Field.create({
            'template_id': template.id,
            'placeholder': 'child_ids',
            'field_path': 'child_ids',
            'is_loop': True,
        })
        # Should NOT raise
        template.action_activate()
        self.assertEqual(template.state, 'active')
