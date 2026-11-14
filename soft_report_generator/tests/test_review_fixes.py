# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Regression tests for the 2026-11-10 review fixes.

Covers:
* invalid .docx content must surface as ``UserError`` (was a raw ``BadZipFile``);
* a template may only render records of its own model (wizard used to accept
  any ``res_model`` from the context and attach the PDF to the wrong record);
* the LibreOffice call must use a per-conversion profile and turn a timeout
  into ``UserError``;
* the Report Generator menus are restricted to the module's user group.
"""

import os
import subprocess
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_simple_docx,
)

PDF_MIXIN = 'odoo.addons.soft_report_generator.models.pdf_converter'


class _FakeLibreOffice:
    """Stand-in for ``subprocess.run`` that writes the expected output file."""

    def __init__(self, output=b'%PDF-1.4 fake'):
        self.output = output
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        out_dir = cmd[cmd.index('--outdir') + 1]
        source = cmd[-1]
        name = os.path.splitext(os.path.basename(source))[0] + '.pdf'
        with open(os.path.join(out_dir, name), 'wb') as handle:
            handle.write(self.output)
        return subprocess.CompletedProcess(cmd, 0, b'', b'')


@tagged('post_install', '-at_install')
class TestReviewFixes(SoftReportGeneratorCommon):

    def test_parse_rejects_non_docx_content(self):
        template = self._build_template(b'this is not a zip file')
        with self.assertRaises(UserError):
            template.action_parse_template()

    def test_parse_accepts_real_docx(self):
        template = self._build_template(make_simple_docx('Hello {{name}}'))
        template.action_parse_template()
        self.assertEqual(template.state, 'ready')
        self.assertEqual(template.field_ids.mapped('placeholder'), ['name'])

    def test_generate_report_rejects_other_model(self):
        template = self._build_template(make_simple_docx('{{name}}'))
        company = self.env['res.company'].search([], limit=1)
        with self.assertRaises(UserError):
            template.generate_report(company)

    def test_generate_report_enforces_template_domain(self):
        """A domain filtered template must reject non-matching records."""
        matching = self._make_partner('Matching Co')
        other = self._make_partner('Other Co')
        template = self._build_template(
            make_simple_docx('Hello {{name}}'), state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name', 'field_path': 'name',
            })],
        )
        template.write({
            'use_domain': True,
            'template_domain': "[('name', '=', 'Matching Co')]",
        })

        with self.assertRaises(UserError):
            template.generate_report(other)
        action = template.generate_report(matching)
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_action_test_report_uses_a_matching_record(self):
        """The test button used to pick the first record, ignoring the domain."""
        matching = self._make_partner('ZZZ Matching Co')
        self._make_partner('AAA Other Co')
        template = self._build_template(
            make_simple_docx('Hello {{name}}'), state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name', 'field_path': 'name',
            })],
        )
        template.write({
            'use_domain': True,
            'template_domain': "[('name', '=', 'ZZZ Matching Co')]",
        })

        action = template.action_test_report()
        attachment_id = int(
            action['url'].rsplit('/', 1)[-1].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(attachment.res_model, 'res.partner')
        self.assertEqual(attachment.res_id, matching.id)

    def test_preview_rejects_record_outside_template_domain(self):
        matching = self._make_partner('Preview Match')
        other = self._make_partner('Preview Other')
        template = self._build_template(
            make_simple_docx('Hello {{name}}'), state='ready',
        )
        template.write({
            'use_domain': True,
            'template_domain': "[('name', '=', 'Preview Match')]",
        })

        with self.assertRaises(UserError):
            template._render_preview_pdf(other)
        with patch.object(
            type(template), '_render_preview_pdf',
            return_value=b'%PDF-1.4 fake',
        ) as render:
            template.action_preview_report()
        self.assertEqual(render.call_args.args[0], matching)

    def test_invalid_template_domain_raises_user_error(self):
        template = self._build_template(make_simple_docx('Hi'))
        template.write({
            'use_domain': True,
            'template_domain': '[(',
        })
        with self.assertRaises(UserError):
            template.generate_report(self._make_partner())

    def test_wizard_rejects_mismatched_res_model(self):
        template = self._build_template(make_simple_docx('{{name}}'))
        company = self.env['res.company'].search([], limit=1)
        wizard = self.env['soft.report.template.wizard'].with_context(
            default_res_model='res.company',
            default_res_ids=[company.id],
            default_available_template_ids=template.ids,
        ).create({'template_id': template.id})
        with self.assertRaises(UserError):
            wizard.action_print()

    def test_convert_format_uses_private_libreoffice_profile(self):
        fake = _FakeLibreOffice()
        with (
            patch(PDF_MIXIN + '.subprocess.run', fake),
            patch(PDF_MIXIN + '.PdfConverterMixin._find_libreoffice',
                  lambda *args, **kwargs: '/usr/bin/soffice'),
        ):
            result = self.env['soft.report.template.pdf.mixin']._convert_format(
                b'docx bytes', 'docx', 'pdf',
            )
        self.assertEqual(result, b'%PDF-1.4 fake')
        profile_args = [a for a in fake.cmd if a.startswith('-env:UserInstallation=')]
        self.assertEqual(len(profile_args), 1, fake.cmd)
        self.assertTrue(
            profile_args[0].startswith('-env:UserInstallation=file://'),
            profile_args[0],
        )

    def test_convert_format_timeout_raises_user_error(self):
        def raise_timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs.get('timeout'))

        with (
            patch(PDF_MIXIN + '.subprocess.run', raise_timeout),
            patch(PDF_MIXIN + '.PdfConverterMixin._find_libreoffice',
                  lambda *args, **kwargs: '/usr/bin/soffice'),
        ):
            with self.assertRaises(UserError):
                self.env['soft.report.template.pdf.mixin']._convert_format(
                    b'docx bytes', 'docx', 'pdf',
                )

    def test_manager_can_deactivate_active_template(self):
        """A non-system Manager must not need ir.actions.server ACL."""
        manager = new_test_user(
            self.env, login='srg_manager@example.com',
            groups='soft_report_generator.group_soft_report_generator_manager',
        )
        template = self._build_template(
            make_simple_docx('Hi {{name}}'),
            state='ready',
            field_ids=[(0, 0, {
                'placeholder': 'name', 'field_path': 'name',
            })],
        )
        template.action_activate()
        self.assertEqual(template.state, 'active')
        template.with_user(manager).action_deactivate()
        self.assertEqual(template.state, 'ready')
        self.assertFalse(template.server_action_id)

    def test_merge_pdfs_unreadable_input_raises_user_error(self):
        mixin = self.env['soft.report.template.pdf.mixin']
        with self.assertRaises(UserError):
            mixin._merge_pdfs([b'not a pdf'])

    def test_menus_are_restricted_to_the_generator_group(self):
        group = self.env.ref('soft_report_generator.group_soft_report_generator_user')
        for xmlid in (
            'soft_report_generator.soft_report_generator_menu_root',
            'soft_report_generator.soft_report_generator_menu_templates',
        ):
            menu = self.env.ref(xmlid)
            self.assertIn(group, menu.group_ids, xmlid)
