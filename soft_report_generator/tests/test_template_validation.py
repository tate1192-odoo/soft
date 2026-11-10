# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for template upload validation: file extension, type compute."""

import base64

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_simple_docx,
)


@tagged('post_install', '-at_install')
class TestTemplateValidation(SoftReportGeneratorCommon):
    """Ensure .docx-only upload contract is enforced.

    Covers BUG-1 (xlsx references removed) + BUG-13 (extension validation).
    """

    def test_docx_upload_succeeds(self):
        docx = make_simple_docx('Hello {{name}}')
        template = self._build_template(docx)
        self.assertTrue(template.exists())
        self.assertEqual(template.template_type, 'docx')

    def test_xlsx_upload_rejected_by_constrain(self):
        with self.assertRaises(ValidationError):
            self._build_template(
                b'fake xlsx bytes',
                template_filename='report.xlsx',
            )

    def test_pdf_upload_rejected_by_constrain(self):
        with self.assertRaises(ValidationError):
            self._build_template(
                b'%PDF-1.4 fake',
                template_filename='report.pdf',
            )

    def test_no_extension_rejected(self):
        with self.assertRaises(ValidationError):
            self._build_template(
                b'no ext',
                template_filename='report',
            )

    def test_template_type_only_docx_in_selection(self):
        sel = dict(self.Template._fields['template_type'].selection)
        self.assertEqual(list(sel.keys()), ['docx'])
        self.assertIn('docx', sel)

    def test_output_format_includes_html_odt_rtf(self):
        sel = dict(self.Template._fields['output_format'].selection)
        self.assertIn('html', sel)
        self.assertIn('odt', sel)
        self.assertIn('rtf', sel)
        # Original and PDF must remain
        self.assertIn('original', sel)
        self.assertIn('pdf', sel)

    def test_template_type_compute_unset_for_unknown(self):
        docx = make_simple_docx('Hello')
        template = self._build_template(docx, name='T1')
        # Renaming to another .docx keeps type
        template.write({'template_filename': 'renamed.docx'})
        self.assertEqual(template.template_type, 'docx')

    def test_template_type_empty_filename_clears(self):
        docx = make_simple_docx('Hello')
        template = self._build_template(docx, name='T1')
        self.assertEqual(template.template_type, 'docx')
        template.write({'template_filename': False})
        self.assertFalse(template.template_type)

    def test_search_filter_xlsx_returns_empty(self):
        """Search filter for xlsx must be empty (data consistent)."""
        domain = [('template_type', '=', 'xlsx')]
        results = self.Template.search(domain)
        self.assertFalse(results)
