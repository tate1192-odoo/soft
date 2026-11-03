# -*- coding: utf-8 -*-
# Copyright (C) 2026 Softteknik Bilişim
# Website: https://softteknik.com
# License: LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html)

import base64
import io

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

    def test_settings_row_exposes_the_switch(self):
        """A <setting> only renders its toggle when the first child is the field.

        The form compiler wires fieldName/fieldSlot from the first <field>
        child; without it the settings screen would show a label and no switch.
        """
        arch = etree.fromstring(
            self.env['res.config.settings'].get_view(view_type='form')['arch'])
        fields = arch.xpath(
            "//setting[@id='show_image_in_report']"
            "/field[@name='show_image_in_report']")
        self.assertEqual(len(fields), 1)

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

    def test_report_header_and_rows_keep_the_same_width(self):
        """The extra header cell bumps colspan_count: no column drifts.

        DB independent on purpose: the tax column depends on the company setup,
        so the header count is measured, never hardcoded.
        """
        self._save_settings(True)
        self.order.write({'order_line': [(0, 0, {
            'display_type': 'line_section',
            'name': 'Consumables',
        })]})
        doc = etree.fromstring(self._render_quotation_html().encode())
        table = doc.xpath("//table[contains(@class,'o_main_table')]")[0]
        header_names = [th.get('name') for th in table.xpath(".//thead//th")]
        self.assertIn('th_image', header_names)
        self.assertIn('td_image', [td.get('name') for td in table.xpath(".//tbody//td")])
        header_cells = len(header_names)
        row_widths = {
            sum(int(td.get('colspan') or 1) for td in row.xpath("./td"))
            for row in table.xpath(".//tbody//tr")
        }
        self.assertEqual(row_widths, {header_cells})
        colspans = {
            int(td.get('colspan'))
            for td in table.xpath(".//tbody//td[@colspan]")
            if int(td.get('colspan')) < 90  # 99 is the note row's own span
        }
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
