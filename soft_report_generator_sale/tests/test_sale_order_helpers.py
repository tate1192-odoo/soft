# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Sale-order binding tests for soft_report_generator_sale.

Covers the two things this bridge adds on top of the model-agnostic core:

* ``has_discount`` / ``has_tax`` computed booleans (usable in ``{{#if}}``);
* the "Print Quotation (Soft Report)" server action bound to ``sale.order``.

The real-DOCX parse test comes from the former ``soft_report_designer`` suite
and guards the ``_normalize_cross_paragraph_placeholders`` regression.
"""

import base64
import os
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_docx_with_table,
)


def _template_path():
    """Absolute path to the sale-order DOCX fixture used by this test."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'files', 'sale_order_quotation_template.docx')


_TEMPLATE_FILENAME = 'sale_order_quotation_template.docx'


@tagged('post_install', '-at_install')
class TestSaleOrderHelpers(SoftReportGeneratorCommon):

    def _make_order(self, discount=0.0, with_tax=False, tax=None):
        product = self.env['product.product'].create({
            'name': 'Report Test Service',
            'type': 'service',
        })
        line = {
            'name': 'Report Test Line',
            'product_id': product.id,
            'product_uom_qty': 1,
            'price_unit': 100.0,
            'discount': discount,
            # explicit: the product may carry the company's default taxes
            'tax_ids': [(6, 0, tax.ids)] if (with_tax and tax) else [(5, 0, 0)],
        }
        return self.env['sale.order'].create({
            'partner_id': self._make_partner().id,
            'order_line': [(0, 0, line)],
        })

    def test_has_discount_and_has_tax_flags(self):
        tax = self.env['account.tax'].create({
            'name': 'Report Test Tax',
            'amount': 10.0,
            'amount_type': 'percent',
        })
        order = self._make_order()
        self.assertFalse(order.has_discount)
        self.assertFalse(order.has_tax)

        order.order_line.discount = 5.0
        self.assertTrue(order.has_discount, 'discount on a line must set has_discount')

        order2 = self._make_order(with_tax=True, tax=tax)
        self.assertTrue(order2.has_tax, 'a line with taxes must set has_tax')
        self.assertFalse(order2.has_discount)

    def test_print_action_is_bound_to_sale_order(self):
        action = self.env.ref('soft_report_generator_sale.action_print_sale_order')
        self.assertEqual(action.model_id.model, 'sale.order')
        self.assertEqual(action.binding_model_id.model, 'sale.order')
        self.assertEqual(action.binding_type, 'report')

    def test_action_parse_sale_order_template(self):
        """Parsing a real sale-order DOCX must not raise NameError."""
        path = _template_path()
        self.assertTrue(
            os.path.isfile(path),
            'Sale-order template missing at %s' % path,
        )
        with open(path, 'rb') as fh:
            docx_bytes = fh.read()
        self.assertTrue(docx_bytes, 'Template file is empty')

        template = self._build_template(
            docx_bytes,
            name='Sale Order Quotation',
            model_ref='sale.model_sale_order',
            template_filename=_TEMPLATE_FILENAME,
        )
        template.action_parse_template()

        placeholders = template.field_ids.mapped('placeholder')
        self.assertTrue(placeholders, 'Parse finished but no placeholders were detected')
        self.assertIn('name', placeholders)

    def test_action_parse_sale_order_template_idempotent(self):
        """Parsing the same template twice yields the same mapping count."""
        path = _template_path()
        with open(path, 'rb') as fh:
            docx_bytes = fh.read()
        template = self._build_template(
            docx_bytes,
            model_ref='sale.model_sale_order',
            template_filename=_TEMPLATE_FILENAME,
        )
        template.action_parse_template()
        first = len(template.field_ids)
        template.write({'template_file': base64.b64encode(docx_bytes)})
        self.assertEqual(len(template.field_ids), first)

    # ------------------------------------------------------------------
    #  PR #47 review: loop children and tax_totals_* must not block Activate
    # ------------------------------------------------------------------

    def test_activate_template_with_lines_and_tax_totals(self):
        docx = make_docx_with_table([
            ['Customer: {{partner_id.name}}'],
            ['{{#order_line}}'],
            [['{{price_subtotal|number}}']],
            ['{{/order_line}}'],
            ['Total: {{tax_totals_total|currency}}'],
        ])
        template = self._build_template(
            docx,
            model_ref='sale.model_sale_order',
            field_ids=[
                (0, 0, {'placeholder': 'partner_id.name',
                        'field_path': 'partner_id.name'}),
                (0, 0, {'placeholder': 'order_line',
                        'field_path': 'order_line', 'is_loop': True}),
                # loop child: relative to sale.order.line, not sale.order
                (0, 0, {'placeholder': 'price_subtotal',
                        'field_path': 'price_subtotal',
                        'loop_parent': 'order_line'}),
                # synthetic value filled from tax_totals at render time
                (0, 0, {'placeholder': 'tax_totals_total',
                        'field_path': 'tax_totals_total',
                        'auto_resolved': True}),
            ],
            state='ready',
        )
        template.action_activate()
        self.assertEqual(template.state, 'active',
                         'a template with a loop must be activatable')
        self.assertEqual(template.server_action_id.binding_type, 'report')

        order = self._make_order()
        context = template._build_render_context(order)
        output = template._render_docx(
            base64.b64decode(template.template_file), context)
        text = self._docx_text(output)
        self.assertIn('Acme', text, 'parent placeholder is printed')
        self.assertIn('100', text, 'loop child resolves on the line record')

    def _docx_text(self, docx_bytes):
        import zipfile
        from io import BytesIO
        from lxml import etree
        from odoo.addons.soft_report_generator.tests.common import W_NS
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            root = etree.fromstring(zf.read('word/document.xml'))
        return ''.join(t.text or '' for t in root.iter('{%s}t' % W_NS))

    # ------------------------------------------------------------------
    #  Odoo 19: product PDF documents are merged after the report
    # ------------------------------------------------------------------

    @staticmethod
    def _pdf_bytes(pages=1):
        """Minimal valid PDF with *pages* blank pages, or None without pypdf."""
        try:
            from pypdf import PdfWriter
        except ImportError:
            return None
        from io import BytesIO
        writer = PdfWriter()
        for _index in range(pages):
            writer.add_blank_page(width=200, height=200)
        buf = BytesIO()
        writer.write(buf)
        return buf.getvalue()

    @staticmethod
    def _page_count(pdf_bytes):
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        from io import BytesIO
        return len(PdfReader(BytesIO(pdf_bytes)).pages)

    def test_product_documents_are_merged(self):
        """A PDF product document must be appended to the rendered report.

        Odoo 19 exposes ``_get_product_documents()`` (records), not
        ``_get_product_documents_pdf()`` (bytes): the old hook matched nothing
        and the advertized merge silently never ran.
        """
        pdf = self._pdf_bytes()
        if pdf is None:
            self.skipTest('pypdf is not installed')
        if 'attached_on_sale' not in self.env['product.document']._fields:
            self.skipTest('sale_pdf_quote_builder is not installed')

        template = self._build_template(
            make_docx_with_table([['{{partner_id.name}}']]),
            model_ref='sale.model_sale_order',
        )
        order = self._make_order()
        document = self.env['product.document'].create({
            'name': 'datasheet.pdf',
            'res_model': 'product.product',
            'res_id': order.order_line.product_id.id,
            'datas': base64.b64encode(pdf),
            'attached_on_sale': 'quotation',
        })
        self.assertEqual(document.mimetype, 'application/pdf')
        self.assertIn(document, order._get_product_documents())

        merged = template._merge_product_documents(order, pdf)
        self.assertEqual(
            self._page_count(merged), 2,
            'report + product document must be merged into one PDF')

    def test_non_pdf_product_documents_are_not_merged(self):
        """A text attachment on the product must not be fed to the PDF merger."""
        pdf = self._pdf_bytes()
        if pdf is None:
            self.skipTest('pypdf is not installed')
        if 'attached_on_sale' not in self.env['product.document']._fields:
            self.skipTest('sale_pdf_quote_builder is not installed')

        template = self._build_template(
            make_docx_with_table([['{{partner_id.name}}']]),
            model_ref='sale.model_sale_order',
        )
        order = self._make_order()
        self.env['product.document'].create({
            'name': 'notes.txt',
            'res_model': 'product.product',
            'res_id': order.order_line.product_id.id,
            'datas': base64.b64encode(b'plain text, not a pdf'),
            'attached_on_sale': 'quotation',
        })
        merged = template._merge_product_documents(order, pdf)
        self.assertEqual(self._page_count(merged), 1)
        self.assertEqual(merged, pdf, 'the input PDF must come back untouched')

    def test_generate_report_routes_the_pdf_through_the_merge(self):
        """The call site: generate_report() must merge, not only the helper."""
        pdf = self._pdf_bytes()
        if pdf is None:
            self.skipTest('pypdf is not installed')
        if 'attached_on_sale' not in self.env['product.document']._fields:
            self.skipTest('sale_pdf_quote_builder is not installed')

        template = self._build_template(
            make_docx_with_table([['{{partner_id.name}}']]),
            model_ref='sale.model_sale_order', state='ready')
        order = self._make_order()
        self.env['product.document'].create({
            'name': 'datasheet.pdf',
            'res_model': 'product.product',
            'res_id': order.order_line.product_id.id,
            'datas': base64.b64encode(pdf),
            'attached_on_sale': 'quotation',
        })
        template.write({'output_format': 'pdf', 'merge_pdf': True})

        # one page out of the converter; the product document has to be added
        with patch.object(
            type(template), '_convert_format',
            lambda _self, data, source, target: pdf,
        ):
            action = template.generate_report(order)

        attachment_id = int(
            action['url'].split('/web/content/')[1].split('?')[0])
        merged = base64.b64decode(
            self.env['ir.attachment'].browse(attachment_id).datas)
        self.assertEqual(
            self._page_count(merged), 2,
            'generate_report() must append the product document')

    def test_merge_without_the_hook_returns_the_report(self):
        """The core stays model-agnostic: a model without the hook is a no-op."""
        pdf = self._pdf_bytes()
        if pdf is None:
            self.skipTest('pypdf is not installed')
        template = self._build_template(make_docx_with_table([['{{name}}']]))
        partner = self._make_partner()
        self.assertFalse(hasattr(partner, '_get_product_documents'))
        self.assertIs(template._merge_product_documents(partner, pdf), pdf)
