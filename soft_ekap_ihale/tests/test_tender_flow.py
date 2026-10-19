from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTenderFlow(TransactionCase):
    """The tender → items → bid → controls flow, with real records."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tender = cls.env["ekap.tender"]
        cls.Bid = cls.env["ekap.bid"]
        cls.uom = cls.env.ref("uom.product_uom_unit")
        cls.rate = cls.env["ekap.labor.rate"].create(
            {
                "gross_minimum_wage": 20_002.50,
                "date_from": "2026-01-01",
                "source": "Test decision",
            }
        )
        cls.tender = cls.Tender.create(
            {
                "tender_no": "2026/123456",
                "contracting_authority": "Test Municipality",
                "tender_type": "services",
                "personnel_based": True,
                "approximate_cost": 1_000_000,
                "limit_value": 900_000,
                "limit_value_source": "contracting_authority",
                "item_ids": [
                    Command.create(
                        {
                            "name": "Cleaning service",
                            "uom_id": cls.uom.id,
                            "quantity": 10,
                            "authority_unit_price": 50_000,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Pest control service",
                            "uom_id": cls.uom.id,
                            "quantity": 5,
                            "authority_unit_price": 20_000,
                        }
                    ),
                ],
            }
        )

    def _make_bid(self):
        bid = self.Bid.create({"tender_id": self.tender.id})
        bid.action_generate_lines()
        return bid

    def test_the_reference_comes_from_the_sequence(self):
        self.assertTrue(self.tender.name.startswith("TENDER/"))
        bid = self._make_bid()
        self.assertTrue(bid.name.startswith("BID/"))

    def test_lines_are_created_from_the_tender_items(self):
        bid = self._make_bid()
        self.assertEqual(len(bid.line_ids), 2)
        self.assertEqual(bid.bid_total, 600_000)
        self.assertEqual(bid.authority_total, 600_000)

    def test_generating_lines_twice_is_refused(self):
        bid = self._make_bid()
        with self.assertRaises(UserError):
            bid.action_generate_lines()

    def test_discount_rewrites_the_unit_prices(self):
        bid = self._make_bid()
        bid.bulk_discount_rate = 10.0
        bid.action_apply_discount()
        self.assertAlmostEqual(bid.line_ids[0].offer_unit_price, 45_000, places=2)
        self.assertAlmostEqual(bid.bid_total, 540_000, places=2)

    def test_an_under_limit_bid_blocks_the_submission_until_explained(self):
        bid = self._make_bid()
        self.assertTrue(bid.abnormally_low)
        self.assertEqual(bid.state, "draft")
        with self.assertRaises(UserError):
            bid.action_submit()
        bid.explanation_ready = True
        bid.action_submit()
        self.assertEqual(bid.state, "submitted")
        self.assertTrue(bid.submitted_on)

    def test_an_under_limit_bid_in_a_rejecting_tender_cannot_be_submitted(self):
        self.tender.reject_without_explanation = True
        bid = self._make_bid()
        self.assertTrue(bid.abnormally_low)
        bid.explanation_ready = True
        with self.assertRaises(UserError):
            bid.action_submit()
        self.assertEqual(bid.state, "draft")
        self.tender.reject_without_explanation = False

    def test_a_bid_above_the_limit_value_needs_no_explanation(self):
        bid = self._make_bid()
        bid.bulk_discount_rate = 0.0
        bid.line_ids.write({"offer_unit_price": 100_000})
        bid.line_ids.flush_recordset()
        self.assertFalse(bid.abnormally_low)
        bid.action_submit()
        self.assertEqual(bid.state, "submitted")

    def test_winning_the_bid_closes_the_tender(self):
        bid = self._make_bid()
        bid.explanation_ready = True
        bid.action_submit()
        bid.action_won()
        self.assertEqual(bid.state, "won")
        self.assertEqual(self.tender.state, "won")

    def test_the_labour_floor_is_computed_from_the_parameters(self):
        calc = self.env["ekap.labor.calc"].create(
            {"tender_id": self.tender.id, "rate_id": self.rate.id, "worker_count": 2, "month_count": 12}
        )
        # Gross 20,002.50 · employer 17.75% · meal 6% · 3% → 25,495.68656 (see test_calculation);
        # Monetary fields round to the currency precision (2 digits), hence 25,495.69.
        self.assertAlmostEqual(calc.minimum_unit_cost, 25_495.69, places=2)
        self.assertAlmostEqual(calc.total_minimum_cost, 611_896.48, places=2)
        self.tender.labor_calc_id = calc
        self.assertTrue(calc.name)

    def test_a_bid_below_the_labour_floor_is_flagged(self):
        calc = self.env["ekap.labor.calc"].create(
            {"tender_id": self.tender.id, "rate_id": self.rate.id}
        )
        self.tender.labor_calc_id = calc
        bid = self._make_bid()
        # The first line stays above the floor; the warning must come from the
        # second line, otherwise the check only inspected line_ids[:1].
        bid.line_ids[0].offer_unit_price = 50_000
        bid.line_ids[1].offer_unit_price = 20_000
        bid.line_ids.flush_recordset()
        self.assertTrue(bid.labor_warning)

    def test_the_amount_parser_accepts_both_notations(self):
        parse = self.env["ekap.limit.value.wizard"]._parse_amounts
        self.assertEqual(parse("7.500.000\n8.000.000"), [7_500_000.0, 8_000_000.0])
        self.assertEqual(parse("7500000.50"), [7_500_000.50])
        self.assertEqual(parse("12.345,67"), [12_345.67])
        self.assertEqual(parse("1.250"), [1_250.0])
        self.assertEqual(parse("9.500.000,25 ; 8000000"), [9_500_000.25, 8_000_000.0])
        with self.assertRaises(UserError):
            parse("fifty million")

    def test_the_limit_value_wizard_writes_the_result_back(self):
        works = self.Tender.create(
            {
                "tender_no": "2026/654321",
                "tender_type": "works",
                "approximate_cost": 10_000_000,
            }
        )
        wizard = (
            self.env["ekap.limit.value.wizard"]
            .with_context(default_tender_id=works.id)
            .create(
                {
                    "tender_id": works.id,
                    "approximate_cost": 10_000_000,
                    "n_coefficient": 1.20,
                    "bid_text": "7.500.000\n8.000.000\n9.000.000\n9.500.000",
                }
            )
        )
        self.assertAlmostEqual(wizard.limit_value, 6_295_045.045045046, places=2)
        self.assertIn("Limit value", wizard.result_html)
        wizard.action_apply()
        self.assertAlmostEqual(works.limit_value, 6_295_045.045045046, places=2)
        self.assertEqual(works.limit_value_source, "computed")

    def test_a_missing_parameter_raises_instead_of_defaulting(self):
        """No rate, no calculation: a silent default would fake a correct bid."""
        with self.assertRaises(UserError):
            self.env["ekap.parameter"].get_value("WORKS_N_OTHER", date="1999-01-01")
        self.assertEqual(self.env["ekap.parameter"].get_value("WORKS_N_OTHER"), 1.20)

    def test_overlapping_parameter_periods_are_refused(self):
        with self.assertRaises(UserError):
            self.env["ekap.parameter"].create(
                {
                    "code": "VAT",
                    "value": 0.10,
                    "date_from": "2024-01-01",
                    "source": "Test",
                }
            )

    def test_the_user_group_can_create_a_tender_and_others_cannot(self):
        outsider = self.env["res.users"].create(
            {"name": "Outside Tender", "login": "ekap_outsider", "group_ids": [Command.set([self.env.ref("base.group_user").id])]}
        )
        with self.assertRaises(AccessError):
            self.Tender.with_user(outsider).create({"tender_no": "2026/999", "tender_type": "goods"})

        member = self.env["res.users"].create(
            {
                "name": "Tender User",
                "login": "ekap_member",
                "group_ids": [
                    Command.set(
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("soft_ekap_ihale.group_ekap_user").id,
                        ]
                    )
                ],
            }
        )
        tender = self.Tender.with_user(member).create({"tender_no": "2026/1000", "tender_type": "goods"})
        self.assertTrue(tender.name.startswith("TENDER/"))
        # Parameters are read-only for a plain user, manager-only to maintain.
        with self.assertRaises(AccessError):
            self.env["ekap.parameter"].with_user(member).create(
                {"code": "VAT", "value": 0.18, "date_from": "2030-01-01", "source": "Test"}
            )

    def test_company_parameter_overrides_the_global_value(self):
        """A company-specific rate wins over the global fallback."""
        company = self.env["res.company"].create({"name": "Parameter Test Co"})
        self.env["ekap.parameter"].create({
            "code": "VAT",
            "value": 0.10,
            "date_from": "2024-01-01",
            "source": "Test company rate",
            "company_id": company.id,
        })
        self.assertEqual(
            self.env["ekap.parameter"].get_value("VAT", company=company), 0.10
        )
        self.assertEqual(self.env["ekap.parameter"].get_value("VAT"), 0.20)

    def test_best_bid_is_the_lowest_non_cancelled_bid(self):
        """The check must follow the cheapest offer, not the latest one."""
        first = self._make_bid()
        second = self._make_bid()
        second.line_ids[0].offer_unit_price = 10_000
        second.line_ids.flush_recordset()

        self.assertGreater(first.bid_total, second.bid_total)
        self.assertEqual(self.tender.best_bid_id, second)


    def test_archived_parameter_keeps_the_bid_screen_readable(self):
        """A missing display parameter must not break the list/form; submit blocks."""
        params = self.env["ekap.parameter"].search([
            ("code", "=", "PROVISIONAL_SECURITY"),
            ("active", "=", True),
        ])
        params.write({"active": False})
        bid = self._make_bid()

        values = bid.read(
            ["provisional_security", "final_security", "final_security_basis"]
        )[0]
        self.assertEqual(values["provisional_security"], 0.0)
        self.assertEqual(values["final_security"], 0.0)
        self.assertIn("PROVISIONAL_SECURITY", values["final_security_basis"])

        with self.assertRaises(UserError):
            bid.action_submit()
        self.assertEqual(bid.state, "draft")

    def test_result_actions_are_multi_record_safe(self):
        """Two bids on two tenders can be closed as one recordset."""
        first = self._make_bid()
        other_tender = self.Tender.create(
            {"tender_no": "2026/777003", "tender_type": "works"}
        )
        second = self.Bid.create({"tender_id": other_tender.id})

        (first | second).action_won()

        self.assertEqual(first.state, "won")
        self.assertEqual(second.state, "won")
        self.assertEqual(self.tender.state, "won")
        self.assertEqual(other_tender.state, "won")
        self.assertEqual(self.tender.winning_firm, first.company_id.name)
        self.assertEqual(other_tender.winning_firm, second.company_id.name)

    def test_a_lost_bid_does_not_hide_another_won_bid(self):
        """The tender stays won while another bid of the same tender won."""
        first = self._make_bid()
        second = self._make_bid()

        first.action_won()
        second.action_lost()

        self.assertEqual(first.state, "won")
        self.assertEqual(second.state, "lost")
        self.assertEqual(self.tender.state, "won")
