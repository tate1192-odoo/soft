"""Regression tests for sale_proforma.

Pins the behaviour the fixes of the 2026-10-15 review established:

* confirming a sales order seeds ``sale_proforma`` from the high-priority
  template — once per batch — and never overwrites existing content;
* an archived high-priority template is not used;
* the shipped data carries the content as separated ``<p>`` blocks (plain
  newlines collapse in the rendered proforma: measured in a real PDF);
* the Proforma page is reachable on quotations too (hidden only when
  cancelled);
* templates became archivable (``active``) and delete is manager-only.

Every test quarantines the templates that already exist in the database
(the shipped record is ``noupdate`` and existing installs keep their edited
copy), so the suite is deterministic on both fresh and upgraded databases.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleProforma(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Proforma Customer"})

    def _quarantine_templates(self):
        """Archive every template present in the database (shipped included)."""
        existing = self.env["sale.proforma.template"].search([])
        if existing:
            existing.write({"active": False})
        return existing

    def _order(self):
        return self.env["sale.order"].create({"partner_id": self.partner.id})

    def test_01_confirm_fills_from_the_high_priority_template(self):
        self._quarantine_templates()
        template = self.env["sale.proforma.template"].create(
            {"name": "High", "proforma": "<p>SEED CONTENT</p>", "priority": "1"}
        )
        order = self._order()

        order.action_confirm()

        self.assertEqual(order.state, "sale")
        self.assertEqual(order.sale_proforma, template.proforma)

    def test_02_confirm_preserves_existing_content(self):
        self._quarantine_templates()
        self.env["sale.proforma.template"].create(
            {"name": "High", "proforma": "<p>SEED CONTENT</p>", "priority": "1"}
        )
        order = self._order()
        order.sale_proforma = "<p>MANUAL CONTENT</p>"

        order.action_confirm()

        self.assertEqual(order.sale_proforma, "<p>MANUAL CONTENT</p>")

    def test_03_confirm_without_template_leaves_it_empty(self):
        self._quarantine_templates()
        order = self._order()

        order.action_confirm()

        self.assertEqual(order.state, "sale")
        self.assertFalse(order.sale_proforma)

    def test_04_archived_template_is_not_used(self):
        self._quarantine_templates()
        self.env["sale.proforma.template"].create(
            {
                "name": "Archived High",
                "proforma": "<p>OLD CONTENT</p>",
                "priority": "1",
                "active": False,
            }
        )
        order = self._order()

        order.action_confirm()

        self.assertFalse(order.sale_proforma)

    def test_05_onchange_loads_the_selected_template(self):
        template = self.env["sale.proforma.template"].create(
            {"name": "Manual", "proforma": "<p>MANUAL PICK</p>"}
        )
        order = self._order()

        order.sale_proforma_template_id = template
        order._set_proformas()

        self.assertEqual(order.sale_proforma, template.proforma)

    def test_06_delete_is_manager_only(self):
        self._quarantine_templates()
        template = self.env["sale.proforma.template"].create(
            {"name": "Deletable", "proforma": "<p>X</p>"}
        )
        salesman = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Proforma Salesman",
                    "login": "proforma_salesman",
                    "password": "proforma_salesman",
                    "group_ids": [
                        (6, 0, [self.env.ref("sales_team.group_sale_salesman").id])
                    ],
                }
            )
        )
        with self.assertRaises(AccessError):
            template.with_user(salesman).unlink()

        manager = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Proforma Manager",
                    "login": "proforma_manager",
                    "password": "proforma_manager",
                    "group_ids": [
                        (6, 0, [self.env.ref("sales_team.group_sale_manager").id])
                    ],
                }
            )
        )
        template.with_user(manager).unlink()
        self.assertFalse(template.exists())

    def test_07_proforma_page_is_reachable_on_quotations(self):
        """Only a cancelled order hides the Proforma page."""
        arch = str(self.env.ref("sale_proforma.sale_order_proforma_add_form_view").arch)
        self.assertIn('name="proforma"', arch)
        self.assertIn("state == 'cancel'", arch)
        self.assertNotIn("state in ['draft', 'sent']", arch)

    def test_08_confirm_uses_the_order_company_template(self):
        """A template from another company is not used on confirm."""
        self._quarantine_templates()
        other_company = self.env["res.company"].create({"name": "Other Proforma Co"})
        self.env["sale.proforma.template"].create({
            "name": "Other Company High",
            "proforma": "<p>OTHER CONTENT</p>",
            "priority": "1",
            "company_id": other_company.id,
        })
        order = self._order()

        order.action_confirm()

        self.assertFalse(order.sale_proforma)

    def test_09_global_template_is_fallback(self):
        """A template without company is used when the order company has none."""
        self._quarantine_templates()
        template = self.env["sale.proforma.template"].create({
            "name": "Global High",
            "proforma": "<p>GLOBAL CONTENT</p>",
            "priority": "1",
            "company_id": False,
        })
        order = self._order()

        order.action_confirm()

        self.assertEqual(order.sale_proforma, template.proforma)

    def test_10_proforma_is_rendered_on_the_sale_order_report(self):
        """The proforma block is present in the printed sale order HTML."""
        order = self._order()
        order.sale_proforma = "<p>REPORT PROFORMA</p>"

        html = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", order.ids
        )[0].decode("utf-8")

        self.assertIn("REPORT PROFORMA", html)
