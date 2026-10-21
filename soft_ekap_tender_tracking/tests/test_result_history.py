"""The award result and the authority history built from the module's own records."""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAwardResult(TransactionCase):
    """A mean is only useful with the ground it stands on: counts travel with it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tender = cls.env["ekap.tender"]
        cls.contracting_authority = "Test Municipality"

        def tender(**vals):
            vals.setdefault("contracting_authority", cls.contracting_authority)
            vals.setdefault("tender_type", "works")
            return cls.Tender.create(vals)

        # 20% and 10% discounts, one result with no published price, one awarded
        # above the estimate (negative discount), one of another tender kind.
        cls.t20 = tender(
            state="lost", approximate_cost=1_000_000, contract_price=800_000,
            valid_bid_count=4,
        )
        cls.t10 = tender(
            state="won", approximate_cost=2_000_000, contract_price=1_800_000,
            valid_bid_count=2,
        )
        cls.tnoprice = tender(
            state="lost", approximate_cost=1_000_000, valid_bid_count=1
        )
        cls.tnegative = tender(
            state="lost", approximate_cost=1_000_000, contract_price=1_100_000
        )
        cls.tservices = tender(
            state="lost", tender_type="services", approximate_cost=1_000_000,
            contract_price=900_000, valid_bid_count=3,
        )
        cls.tother = tender(
            contracting_authority="Other Municipality", state="lost", approximate_cost=1_000_000,
            contract_price=500_000, valid_bid_count=2,
        )

    def test_discount_is_estimate_to_contract(self):
        self.assertAlmostEqual(self.t20.discount_rate, 20.0, places=4)
        self.assertAlmostEqual(self.t10.discount_rate, 10.0, places=4)

    def test_a_contract_above_the_estimate_keeps_the_sign(self):
        self.assertAlmostEqual(self.tnegative.discount_rate, -10.0, places=4)

    def test_no_contract_price_means_no_discount(self):
        self.assertEqual(self.tnoprice.discount_rate, 0.0)

    def test_history_counts_what_it_used(self):
        history = self.Tender._authority_history(self.contracting_authority, "works")
        # four concluded results of this authority and kind; the one without a
        # contract price is counted but cannot enter the mean
        self.assertEqual(history["considered"], 4)
        self.assertEqual(history["used"], 3)
        self.assertAlmostEqual(history["mean_discount"], (20.0 + 10.0 - 10.0) / 3, places=4)
        self.assertAlmostEqual(history["mean_valid_bids"], 3.0, places=4)

    def test_history_excludes_the_record_being_filled(self):
        history = self.Tender._authority_history(self.contracting_authority, "works", exclude_id=self.t10.id)
        self.assertEqual(history["considered"], 3)
        self.assertEqual(history["used"], 2)
        self.assertAlmostEqual(history["mean_discount"], 5.0, places=4)

    def test_history_is_scoped_by_tender_kind(self):
        history = self.Tender._authority_history(self.contracting_authority, "services")
        self.assertEqual(history["considered"], 1)
        self.assertEqual(history["used"], 1)
        self.assertAlmostEqual(history["mean_discount"], 10.0, places=4)

    def test_history_of_an_unknown_authority_is_empty(self):
        history = self.Tender._authority_history("Nobody Municipality", "works")
        self.assertEqual(history["considered"], 0)
        self.assertEqual(history["used"], 0)
        self.assertEqual(history["mean_discount"], 0.0)

    def test_the_history_line_quotes_its_base(self):
        # t10's own row is left out, so the line reports over the other 3 results,
        # 2 of which carry a contract price
        self.assertIn("2 of 3 recorded results", self.t10.authority_history)
        self.assertIn("5.00", self.t10.authority_history)
        self.assertIn("4.0 valid bids", self.t10.authority_history)

    def test_the_history_line_says_when_there_is_nothing_to_say(self):
        self.assertIn(
            "Enter the contracting authority",
            self.Tender.new({}).authority_history,
        )
        fresh = self.Tender.create({"contracting_authority": "Nobody Municipality", "tender_type": "works"})
        self.assertIn("No concluded tender of this authority", fresh.authority_history)

    def test_the_result_filters_are_searchable(self):
        self.assertIn(self.tnoprice, self.Tender.search([("valid_bid_count", "=", 1)]))
        self.assertIn(self.tnegative, self.Tender.search([("discount_rate", "<", 0)]))

    def test_winning_our_own_bid_names_the_winner_once(self):
        tender = self.Tender.create({"tender_no": "2026/777001", "tender_type": "works"})
        bid = self.env["ekap.bid"].create({"tender_id": tender.id})
        bid.action_won()
        self.assertEqual(bid.state, "won")
        self.assertEqual(tender.state, "won")
        self.assertEqual(tender.winning_firm, bid.company_id.name)

        # a winner typed from the result notice is never overwritten
        other = self.Tender.create(
            {"tender_no": "2026/777002", "tender_type": "works", "winning_firm": "Manual Entry Ltd"}
        )
        other_bid = self.env["ekap.bid"].create({"tender_id": other.id})
        other_bid.action_won()
        self.assertEqual(other.winning_firm, "Manual Entry Ltd")
