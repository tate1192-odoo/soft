from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEkapTenderTracking(TransactionCase):
    """Outcome fields and the next-bid reference calculations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom = cls.env.ref("uom.product_uom_unit")

    def _tender(self):
        return self.env["ekap.tender"].create(
            {
                "tender_type": "works",
                "approximate_cost": 1_000_000,
                "item_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Work item",
                            "uom_id": self.uom.id,
                            "quantity": 1,
                            "authority_unit_price": 500_000,
                        },
                    )
                ],
            }
        )

    def _bid(self, tender, price=500_000):
        bid = self.env["ekap.bid"].create({"tender_id": tender.id})
        bid.action_generate_lines()
        bid.line_ids[0].offer_unit_price = price
        bid.line_ids.flush_recordset()
        return bid

    def test_gap_is_negative_when_our_bid_is_higher(self):
        tender = self._tender()
        self._bid(tender, 500_000)
        tender.write({"winning_bid_amount": 480_000})

        self.assertAlmostEqual(tender.price_gap, -20_000, places=2)
        self.assertAlmostEqual(tender.price_gap_percent, -4.17, places=2)

    def test_gap_is_positive_when_our_bid_is_lower(self):
        tender = self._tender()
        self._bid(tender, 450_000)
        tender.write({"winning_bid_amount": 500_000})

        self.assertAlmostEqual(tender.price_gap, 50_000, places=2)
        self.assertAlmostEqual(tender.price_gap_percent, 10.0, places=2)

    def test_gap_is_zero_without_a_winning_bid_or_our_bid(self):
        tender = self._tender()
        self.assertEqual(tender.price_gap, 0.0)
        self.assertEqual(tender.price_gap_percent, 0.0)

        self._bid(tender, 500_000)
        self.assertEqual(tender.price_gap, 0.0)

    def test_tracking_fields_are_on_the_tender_form(self):
        arch = str(self.env.ref("ekap_tender_tracking.view_ekap_tender_tracking_form").arch)
        self.assertIn('name="tracking"', arch)
        self.assertIn('name="our_rank"', arch)
        self.assertIn('name="loss_reason"', arch)
        self.assertIn('name="next_bid_note"', arch)
