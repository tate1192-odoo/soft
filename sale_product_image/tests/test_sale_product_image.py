# -*- coding: utf-8 -*-
# Copyright (C) 2026 Softteknik Bilişim
# Website: https://softteknik.com
# License: LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html)

import base64
import io
import re

from lxml import etree

from PIL import Image

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PARAM_SHOW_IN_REPORT = 'sale_product_image.show_image_in_report'


@tagged('post_install', '-at_install')
class TestSaleProductImage(TransactionCase):
    """Line column is per-user optional; the report column is switch gated."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Image Test Customer'})

        # transparent PNG: the report path must re-encode it to an opaque JPEG
        raw = io.BytesIO()
        Image.new('RGBA', (64, 48), (200, 30, 30, 120)).save(raw, format='PNG')
        cls.product = cls.env['product.product'].create({
            'name': 'Image Test Product',
            'sale_ok': True,
            'list_price': 10.0,
            'image_1920': base64.b64encode(raw.getvalue()),
        })
        cls.plain_product = cls.env['product.product'].create({
            'name': 'Plain Test Product',
            'sale_ok': True,
            'list_price': 5.0,
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 2,
            })],
        })
        cls.line = cls.order.order_line
        cls.plain_order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.plain_product.id,
                'product_uom_qty': 1,
            })],
        })

    def _save_settings(self, show_report):
        """Toggle the report switch the way the settings screen does."""
        self.env['res.config.settings'].create({
            'show_image_in_report': show_report,
        }).execute()

    def _render_quotation_html(self, order=None):
        order = order or self.order
        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'sale.report_saleorder', order.ids)
        return html.decode() if isinstance(html, bytes) else html

    def test_line_column_is_user_toggleable(self):
        """The line column carries optional="show": each user hides it himself."""
        arch = etree.fromstring(
            self.env['sale.order'].get_view(view_type='form')['arch'])
        fields = arch.xpath("//field[@name='order_line_image']")
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].get('optional'), 'show')
        self.assertIsNone(fields[0].get('column_invisible'))

    def test_settings_switch_drives_the_report_column(self):
        """The checkbox stores the parameter the report template reads."""
        self._save_settings(True)
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param(
                PARAM_SHOW_IN_REPORT),
            'True')
        html = self._render_quotation_html()
        self.assertIn('name="th_image"', html)
        self.assertIn('name="td_image"', html)

        self._save_settings(False)
        self.assertFalse(
            self.env['ir.config_parameter'].sudo().get_param(
                PARAM_SHOW_IN_REPORT))
        html = self._render_quotation_html()
        self.assertNotIn('name="th_image"', html)
        self.assertNotIn('name="td_image"', html)

    def test_stored_false_string_keeps_the_column_hidden(self):
        """A parameter written as the string 'False' must not read as on."""
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_SHOW_IN_REPORT, 'False')
        html = self._render_quotation_html()
        self.assertNotIn('name="th_image"', html)
        self.assertNotIn('name="td_image"', html)

    def test_report_column_hidden_when_no_line_has_an_image(self):
        """Switch on but nothing to print: no empty column in the PDF."""
        self._save_settings(True)
        html = self._render_quotation_html(self.plain_order)
        self.assertNotIn('name="th_image"', html)
        self.assertNotIn('name="td_image"', html)

    def test_report_header_colspan_with_image_column(self):
        """The extra header cell bumps colspan_count: section rows stay aligned."""
        self._save_settings(True)
        self.order.write({'order_line': [(0, 0, {
            'display_type': 'line_section',
            'name': 'Consumables',
        })]})
        html = self._render_quotation_html()
        self.assertIn('name="th_image"', html)
        self.assertIn('name="td_image"', html)
        header_cells = len(re.findall(r'<th name="th_', html))
        self.assertEqual(header_cells, 6)  # description, image, qty, price, taxes, amount
        colspans = {int(value) for value in re.findall(r'colspan="(\d+)"', html)}
        self.assertEqual(colspans, {header_cells - 1})

    def test_order_line_image_comes_from_product(self):
        self.assertTrue(self.line.order_line_image)
        self.assertEqual(self.line.order_line_image, self.product.image_128)

    def test_image_for_report_is_opaque_jpeg(self):
        """Transparent PNG in, white-background JPEG out."""
        self.assertTrue(self.line.image_for_report)
        data = base64.b64decode(self.line.image_for_report)
        self.assertTrue(data.startswith(b'\xff\xd8'), 'not a JPEG stream')
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.mode, 'RGB')
