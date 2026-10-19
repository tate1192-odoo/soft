"""Regression tests for sale_agreement.

Pins the behaviour the 2026-10-15 review fixes established:

* confirming a sales order seeds ``sale_agreement`` from the high-priority
  template of the order's company — once per batch — and never overwrites
  existing content;
* the template pick respects the company (no cross-company seeding);
* the onchange loads the picked template and clears the field when the
  template is cleared;
* the Agreement page is reachable on quotations too (hidden only when
  cancelled);
* delete is manager-only.

Every test quarantines the templates that already exist in the database,
so the suite is deterministic on both fresh and upgraded databases.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleAgreement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Agreement Customer"})

    def _quarantine_templates(self):
        """Archive every template present in the database."""
        existing = self.env["sale.agreement.template"].search([])
        if existing:
            existing.write({"active": False})
        return existing

    def _order(self, company=None):
        order_env = self.env["sale.order"]
        if company:
            order_env = order_env.with_company(company)
        return order_env.create({"partner_id": self.partner.id})

    def test_01_confirm_fills_from_the_high_priority_template(self):
        self._quarantine_templates()
        template = self.env["sale.agreement.template"].create(
            {"name": "High", "agreement": "<p>SEED AGREEMENT</p>", "priority": "1"}
        )
        order = self._order()

        order.action_confirm()

        self.assertEqual(order.state, "sale")
        self.assertEqual(order.sale_agreement, template.agreement)

    def test_02_confirm_preserves_existing_content(self):
        self._quarantine_templates()
        self.env["sale.agreement.template"].create(
            {"name": "High", "agreement": "<p>SEED AGREEMENT</p>", "priority": "1"}
        )
        order = self._order()
        order.sale_agreement = "<p>MANUAL AGREEMENT</p>"

        order.action_confirm()

        self.assertEqual(order.sale_agreement, "<p>MANUAL AGREEMENT</p>")

    def test_03_confirm_without_template_leaves_it_empty(self):
        self._quarantine_templates()
        order = self._order()

        order.action_confirm()

        self.assertEqual(order.state, "sale")
        self.assertFalse(order.sale_agreement)

    def test_04_archived_template_is_not_used(self):
        self._quarantine_templates()
        self.env["sale.agreement.template"].create(
            {
                "name": "Archived High",
                "agreement": "<p>OLD</p>",
                "priority": "1",
                "active": False,
            }
        )
        order = self._order()

        order.action_confirm()

        self.assertFalse(order.sale_agreement)

    def test_05_template_is_picked_per_order_company(self):
        """A high-priority template of another company is not used."""
        self._quarantine_templates()
        other_company = self.env["res.company"].create({"name": "Other Agreement Co"})
        self.env["sale.agreement.template"].create(
            {
                "name": "Other Co High",
                "agreement": "<p>OTHER CO</p>",
                "priority": "1",
                "company_id": other_company.id,
            }
        )
        order = self._order()  # main company

        order.action_confirm()

        self.assertFalse(order.sale_agreement)

    def test_06_onchange_loads_and_clears_the_selected_template(self):
        template = self.env["sale.agreement.template"].create(
            {"name": "Manual", "agreement": "<p>MANUAL PICK</p>"}
        )
        order = self._order()

        order.sale_agreement_template_id = template
        order._onchange_sale_agreement_template_id()
        self.assertEqual(order.sale_agreement, template.agreement)

        order.sale_agreement_template_id = False
        order._onchange_sale_agreement_template_id()
        self.assertFalse(order.sale_agreement)

    def test_07_delete_is_manager_only(self):
        self._quarantine_templates()
        template = self.env["sale.agreement.template"].create(
            {"name": "Deletable", "agreement": "<p>X</p>"}
        )
        salesman = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Agreement Salesman",
                    "login": "agreement_salesman",
                    "password": "agreement_salesman",
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
                    "name": "Agreement Manager",
                    "login": "agreement_manager",
                    "password": "agreement_manager",
                    "group_ids": [
                        (6, 0, [self.env.ref("sales_team.group_sale_manager").id])
                    ],
                }
            )
        )
        template.with_user(manager).unlink()
        self.assertFalse(template.exists())

    def test_08_agreement_page_is_reachable_on_quotations(self):
        """Only a cancelled order hides the Agreement page."""
        arch = str(self.env.ref("sale_agreement.sale_agreement_add_form_view").arch)
        self.assertIn('name="agreement"', arch)
        self.assertIn("state == 'cancel'", arch)
        self.assertNotIn("state in ['draft', 'sent']", arch)

    def test_09_agreement_is_rendered_on_the_sale_order_report(self):
        """The agreement block is present in the printed sale order HTML."""
        order = self._order()
        order.sale_agreement = "<p>REPORT AGREEMENT</p>"

        html = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", order.ids
        )[0].decode("utf-8")

        self.assertIn("REPORT AGREEMENT", html)
