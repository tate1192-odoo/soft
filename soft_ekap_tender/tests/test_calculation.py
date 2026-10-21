"""Unit tests of the calculation rules — no ORM involved.

Every expected number is written by hand from the legislation, so a change in the
engine has to argue with the test instead of with a moving reference.
"""

from odoo.addons.soft_ekap_tender.models.calculation import (
    check_abnormally_low,
    labor_cost,
    limit_value_services,
    limit_value_works,
    securities,
    stamp_duties,
    vat_excluded,
    vat_included,
)
from odoo.addons.soft_ekap_tender.models.calculation.limit_value import CalculationError
from odoo.tests.common import BaseCase, tagged


@tagged("post_install", "-at_install")
class TestLimitValue(BaseCase):
    """KGT 45.1.1 (construction works) and 79.1.2 (services)."""

    def test_works_limit_value_follows_45_1_1(self):
        """AC 10,000,000, N 1.20, bids 7.5M / 8M / 9M / 9.5M.

        Tort1 = 8,500,000 · σ = 912,870.929 (n−1) · band [7,587,129.07 ; 9,412,870.93]
        → Tort2 = (8,000,000 + 9,000,000) / 2 = 8,500,000 · C = 0.85
        → K = (3.2 × 0.85 − 0.85² − 0.6) / 1.85 = 0.7554054054
        → SD = (K × Tort2) / (C × N) = 6,295,045.045
        """
        result = limit_value_works(10_000_000, [7_500_000, 8_000_000, 9_000_000, 9_500_000], 1.20, detail=True)
        self.assertAlmostEqual(result["tort1"], 8_500_000.0, places=2)
        self.assertAlmostEqual(result["sigma"], 912_870.9291752769, places=4)
        self.assertAlmostEqual(result["tort2"], 8_500_000.0, places=2)
        self.assertAlmostEqual(result["c"], 0.85, places=6)
        self.assertAlmostEqual(result["k"], 0.7554054054054056, places=9)
        self.assertAlmostEqual(result["limit_value"], 6_295_045.045045046, places=4)

    def test_works_uses_the_sample_standard_deviation(self):
        """KGT 45.1.1 uses n-1; this set changes the Tort2 band if n is used.

        Bids 440k / 865k / 1,046k, AC 1,000,000, N 1.20:
        population band [865,000] → SD 634,394.55;
        sample band [865,000; 1,046,000] → Tort2 955,500 → SD 658,237.34.
        """
        result = limit_value_works(
            1_000_000, [440_000, 865_000, 1_046_000], 1.20, detail=True
        )
        self.assertAlmostEqual(result["sigma"], 311_079.3039296143, places=4)
        self.assertEqual(result["band_bids"], [865_000.0, 1_046_000.0])
        self.assertAlmostEqual(result["tort2"], 955_500.0, places=2)
        self.assertAlmostEqual(result["limit_value"], 658_237.3433904373, places=2)

    def test_works_discards_bids_outside_the_40_120_band(self):
        """Bids above AC×1.20 and below AC×0.40 never enter Tort1."""
        result = limit_value_works(
            1_000_000, [300_000, 800_000, 900_000, 1_500_000], 1.20, detail=True
        )
        self.assertEqual(sorted(result["valid_bids"]), [800_000.0, 900_000.0])

    def test_works_single_bid_gives_that_bid_as_tort2(self):
        """A single bid of 800,000 · AC 1,000,000 → C = 0.8, K = 0.7333…

        SD = (K × Tort2) / (C × N) = 586,666.67 / 0.96 = 611,111.11
        """
        result = limit_value_works(1_000_000, [800_000], 1.20, detail=True)
        self.assertEqual(result["sigma"], 0.0)
        self.assertEqual(result["tort2"], 800_000.0)
        # C = 0.8 → K = (3.2 × 0.8 − 0.64 − 0.6) / 1.8 = 0.733333…
        self.assertAlmostEqual(result["k"], 0.7333333333333333, places=9)
        self.assertAlmostEqual(result["limit_value"], 611_111.1111111114, places=2)

    def test_works_limit_value_never_below_40_percent_of_the_cost(self):
        """AC 1,000,000 with a single very low bid → the 400,000 floor applies."""
        sd = limit_value_works(1_000_000, [400_000], 1.20)
        self.assertEqual(sd, 400_000.0)

    def test_works_rejects_an_unusable_bid_set(self):
        with self.assertRaises(CalculationError):
            limit_value_works(1_000_000, [100_000], 1.20)

    def test_services_limit_value_follows_79_1_2(self):
        """AC 1,000,000, bids 700k / 800k / 900k / 1.2M, R 0.78.

        The 1.2M bid is above the AC and the 60% floor leaves 700k/800k/900k:
        SD = ((1,000,000 + 2,400,000) / 4) × 0.78 = 663,000.
        """
        self.assertAlmostEqual(limit_value_services(1_000_000, [700_000, 800_000, 900_000, 1_200_000], 0.78), 663_000.0, places=2)

    def test_services_rejects_a_bid_set_without_valid_bids(self):
        with self.assertRaises(CalculationError):
            limit_value_services(1_000_000, [100_000, 1_500_000], 0.78)

    def test_abnormally_low_states(self):
        alt = check_abnormally_low(900_000, 1_000_000, "works")
        self.assertTrue(alt["abnormally_low"])
        self.assertEqual(alt["status"], "explanation_required")
        ust = check_abnormally_low(1_100_000, 1_000_000, "works")
        self.assertFalse(ust["abnormally_low"])
        esik = check_abnormally_low(900_000, 1_000_000, "works", explanation_threshold_exceeded=True)
        self.assertEqual(esik["status"], "rejected")
        mal = check_abnormally_low(100, 1_000_000, "goods")
        self.assertFalse(mal["abnormally_low"])
        self.assertEqual(mal["status"], "commission_assessment")
        not_entered = check_abnormally_low(900_000, 0, "works")
        self.assertEqual(not_entered["status"], "limit_value_unknown")


@tagged("post_install", "-at_install")
class TestLabour(BaseCase):
    """KGT 79.7 — the labour floor must match the KİK tool's arithmetic."""

    RATES = {
        "EMPLOYEE_SOCIAL_SECURITY": 0.14,
        "EMPLOYEE_UNEMPLOYMENT": 0.01,
        "EMPLOYER_SS_REDUCED": 0.1575,
        "EMPLOYER_SS_FULL": 0.2075,
        "EMPLOYER_UNEMPLOYMENT": 0.02,
        "MEAL_RATE": 0.06,
        "CONTRACT_OVERHEAD": 0.03,
    }

    def test_labour_floor_of_one_worker_month(self):
        """Gross 20,002.50 · employer 17.75% · meal 6% · 3% → 25,495.68656."""
        result = labor_cost(20_002.50, self.RATES)
        self.assertAlmostEqual(result["employer_social_security"], 3_550.44375, places=6)
        self.assertAlmostEqual(result["meal"], 1_200.15, places=6)
        self.assertAlmostEqual(result["total_without_profit"], 24_753.09375, places=6)
        self.assertAlmostEqual(result["contract_overhead"], 742.5928125, places=6)
        self.assertAlmostEqual(result["minimum_unit_cost"], 25_495.6865625, places=6)
        self.assertAlmostEqual(result["minimum_hourly_cost"], 113.3141625, places=6)
        self.assertAlmostEqual(result["total_minimum_cost"], 25_495.6865625, places=6)

    def test_employer_share_without_the_five_point_discount(self):
        result = labor_cost(20_002.50, self.RATES, employer_ss_reduction=False)
        self.assertAlmostEqual(result["employer_ss_rate"], 0.2275, places=6)

    def test_scale_with_worker_count_and_months(self):
        result = labor_cost(20_002.50, self.RATES, worker_count=4, month_count=12)
        self.assertAlmostEqual(result["total_minimum_cost"], 25_495.6865625 * 48, places=4)

    def test_overtime_uses_the_hourly_wage(self):
        result = labor_cost(
            20_002.50, self.RATES, overtime_hours_monthly=20, monthly_working_hours=225
        )
        expected = (20_002.50 / 225) * 1.5 * 20
        self.assertAlmostEqual(result["overtime"], expected, places=6)


@tagged("post_install", "-at_install")
class TestSecuritiesAndTax(BaseCase):
    def test_provisional_and_final_securities(self):
        result = securities(1_000_000, 0.03, 0.06)
        self.assertAlmostEqual(result["provisional_security"], 30_000.0, places=2)
        self.assertAlmostEqual(result["final_security"], 60_000.0, places=2)

    def test_construction_bid_below_the_limit_values_the_cost(self):
        """Law 4734 art.43: a construction bid below the limit value values the final security on the AC."""
        result = securities(
            1_000_000,
            0.03,
            0.06,
            approximate_cost=2_000_000,
            limit_value=1_500_000,
            works=True,
            final_below_limit_rate=0.09,
        )
        self.assertAlmostEqual(result["final_security"], 180_000.0, places=2)
        self.assertEqual(result["final_rate"], 0.09)

    def test_a_service_bid_below_the_limit_keeps_the_six_percent_rule(self):
        result = securities(
            1_000_000,
            0.03,
            0.06,
            approximate_cost=2_000_000,
            limit_value=1_500_000,
            works=False,
            final_below_limit_rate=0.09,
        )
        self.assertAlmostEqual(result["final_security"], 60_000.0, places=2)

    def test_stamp_duty_of_the_award_and_of_the_contract(self):
        result = stamp_duties(1_000_000, 1_000_000, 0.00569, 0.00948)
        self.assertAlmostEqual(result["award_stamp_duty"], 5_690.0, places=2)
        self.assertAlmostEqual(result["contract_stamp_duty"], 9_480.0, places=2)

    def test_vat_round_trip(self):
        self.assertAlmostEqual(vat_excluded(1_200_000, 0.20), 1_000_000.0, places=2)
        self.assertAlmostEqual(vat_included(1_000_000, 0.20), 1_200_000.0, places=2)
