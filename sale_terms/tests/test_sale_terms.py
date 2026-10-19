"""Regression tests for sale_terms.

Pins the behaviour the 2026-10-15 review fixes established:

* creating an order MATERIALISES the terms content from the linked default
  templates (previously only the reference was set and the printed documents
  carried no terms — measured on live orders); existing content is never
  overwritten;
* archived high-priority templates are not linked;
* the template pick respects the company;
* batch create fills every order;
* the onchange methods fill the matching content field;
* delete is manager-only.

Every test quarantines the templates that already exist in the database
(the shipped records are noupdate and live databases carry their own), so
the suite is deterministic on both fresh and upgraded databases.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleTerms(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Terms Customer"})

    def _quarantine_templates(self):
        """Archive every template present in the database."""
        existing = self.env["sale.terms.template"].search([])
        if existing:
            existing.write({"active": False})
        return existing

    def _template(self, position, company=None, content=None):
        vals = {
            "name": f"Probe {position}",
            "position": position,
            "priority": "1",
            "terms": content or f"<p>TERMS {position.upper()}</p>",
        }
        if company:
            vals["company_id"] = company.id
        return self.env["sale.terms.template"].create(vals)

    def test_01_create_materialises_both_terms(self):
        self._quarantine_templates()
        up = self._template("up")
        down = self._template("down")

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertEqual(order.sale_terms_temp_up_id, up)
        self.assertEqual(order.sale_terms_up, up.terms)
        self.assertEqual(order.sale_terms_temp_down_id, down)
        self.assertEqual(order.sale_terms_down, down.terms)

    def test_02_create_preserves_explicit_content(self):
        self._quarantine_templates()
        self._template("up")

        order = self.env["sale.order"].create(
            {"partner_id": self.partner.id, "sale_terms_up": "<p>MANUAL UP</p>"}
        )

        self.assertEqual(order.sale_terms_up, "<p>MANUAL UP</p>")

    def test_03_create_without_templates_leaves_content_empty(self):
        self._quarantine_templates()

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertFalse(order.sale_terms_temp_up_id)
        self.assertFalse(order.sale_terms_up)
        self.assertFalse(order.sale_terms_down)

    def test_04_archived_template_is_not_linked(self):
        self._quarantine_templates()
        template = self._template("up")
        template.active = False

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertFalse(order.sale_terms_temp_up_id)
        self.assertFalse(order.sale_terms_up)

    def test_05_template_is_picked_per_company(self):
        self._quarantine_templates()
        other_company = self.env["res.company"].create({"name": "Other Terms Co"})
        self._template("up", company=other_company)

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertFalse(order.sale_terms_temp_up_id)
        self.assertFalse(order.sale_terms_up)

    def test_06_batch_create_fills_every_order(self):
        self._quarantine_templates()
        up = self._template("up")

        orders = self.env["sale.order"].create(
            [{"partner_id": self.partner.id}, {"partner_id": self.partner.id}]
        )

        self.assertEqual(len(orders), 2)
        for order in orders:
            self.assertEqual(order.sale_terms_up, up.terms)

    def test_07_onchange_fills_the_matching_field(self):
        self._quarantine_templates()
        up = self._template("up")
        down = self._template("down")

        order = self.env["sale.order"].new({"partner_id": self.partner.id})
        order.sale_terms_temp_up_id = up
        order._set_terms1()
        self.assertEqual(order.sale_terms_up, up.terms)

        order.sale_terms_temp_down_id = down
        order._set_terms2()
        self.assertEqual(order.sale_terms_down, down.terms)

    def test_08_delete_is_manager_only(self):
        self._quarantine_templates()
        template = self._template("down")
        salesman = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Terms Salesman",
                    "login": "terms_salesman",
                    "password": "terms_salesman",
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
                    "name": "Terms Manager",
                    "login": "terms_manager",
                    "password": "terms_manager",
                    "group_ids": [
                        (6, 0, [self.env.ref("sales_team.group_sale_manager").id])
                    ],
                }
            )
        )
        template.with_user(manager).unlink()
        self.assertFalse(template.exists())

    def test_09_shipped_defaults_materialise_on_create(self):
        """The shipped down template is high priority and both defaults print."""
        up = self.env.ref("sale_terms.sale_terms_template_2")
        down = self.env.ref("sale_terms.sale_terms_template_1")
        self.assertEqual(down.priority, "1")

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertEqual(order.sale_terms_temp_up_id, up)
        self.assertEqual(order.sale_terms_temp_down_id, down)
        self.assertEqual(order.sale_terms_up, up.terms)
        self.assertEqual(order.sale_terms_down, down.terms)

    def test_10_global_template_is_fallback(self):
        """A template without company is used when the company has no own one."""
        self._quarantine_templates()
        global_up = self.env["sale.terms.template"].create({
            "name": "Global Terms Up",
            "position": "up",
            "priority": "1",
            "company_id": False,
            "terms": "<p>GLOBAL UP</p>",
        })

        order = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.assertEqual(order.sale_terms_temp_up_id, global_up)
        self.assertEqual(order.sale_terms_up, global_up.terms)

    def test_11_terms_are_rendered_on_the_sale_order_report(self):
        """The up/down terms are present in the printed sale order HTML."""
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "sale_terms_up": "<p>REPORT UP</p>",
            "sale_terms_down": "<p>REPORT DOWN</p>",
        })

        html = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", order.ids
        )[0].decode("utf-8")

        self.assertIn("REPORT UP", html)
        self.assertIn("REPORT DOWN", html)

    def test_12_upgrade_fixes_shipped_down_priority(self):
        """An upgraded database gets the priority fix for the shipped template."""
        down = self.env.ref("sale_terms.sale_terms_template_1")
        down.priority = "0"
        down._fix_sale_terms_default_priority()
        self.assertEqual(down.priority, "1")
