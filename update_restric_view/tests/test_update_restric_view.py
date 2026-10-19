import ast

from lxml import etree
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUpdateRestricView(TransactionCase):
    """The inherited views must disable create options without dropping core ones."""

    def _options_at(self, model, view_xmlid, xpath):
        arch = self.env[model].get_view(self.env.ref(view_xmlid).id, "form")["arch"]
        root = etree.fromstring(arch)
        nodes = root.xpath(xpath)
        self.assertTrue(nodes, f"No node for {xpath} in {view_xmlid}")
        options = nodes[0].get("options")
        self.assertTrue(options, f"No options for {xpath} in {view_xmlid}")
        return ast.literal_eval(options)

    def _assert_create_disabled(self, model, view_xmlid, xpath):
        options = self._options_at(model, view_xmlid, xpath)
        self.assertTrue(options.get("no_create"), (model, xpath, options))
        self.assertTrue(options.get("no_quick_create"), (model, xpath, options))
        self.assertTrue(options.get("no_create_edit"), (model, xpath, options))
        return options

    def test_sale_partner_field_disables_quick_create(self):
        self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='partner_id'][1]",
        )

    def test_sale_line_product_fields_disable_quick_create(self):
        self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='order_line']/list//field[@name='product_id'][1]",
        )
        self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='order_line']/form//field[@name='product_id'][1]",
        )
        self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='order_line']/list//field[@name='product_template_id'][1]",
        )

    def test_purchase_line_product_field_disables_quick_create(self):
        self._assert_create_disabled(
            "purchase.order",
            "purchase.purchase_order_form",
            "//field[@name='order_line']/list//field[@name='product_id'][1]",
        )
        self._assert_create_disabled(
            "purchase.order",
            "purchase.purchase_order_form",
            "//field[@name='order_line']/form//field[@name='product_id'][1]",
        )

    def test_core_product_label_warning_is_preserved(self):
        sale_options = self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='order_line']/list//field[@name='product_id'][1]",
        )
        self.assertTrue(sale_options.get("show_label_warning"))
        sale_template_options = self._assert_create_disabled(
            "sale.order",
            "sale.view_order_form",
            "//field[@name='order_line']/list//field[@name='product_template_id'][1]",
        )
        self.assertTrue(sale_template_options.get("show_label_warning"))
        purchase_options = self._assert_create_disabled(
            "purchase.order",
            "purchase.purchase_order_form",
            "//field[@name='order_line']/list//field[@name='product_id'][1]",
        )
        self.assertTrue(purchase_options.get("show_label_warning"))
