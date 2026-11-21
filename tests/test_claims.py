import unittest

from src.decide.claims import commenced_weeks, late_delivery_damages


class ClaimsArithmeticTests(unittest.TestCase):
    def test_commenced_weeks_uses_full_started_week(self):
        self.assertEqual(commenced_weeks(1), 1)
        self.assertEqual(commenced_weeks(7), 1)
        self.assertEqual(commenced_weeks(8), 2)
        self.assertEqual(commenced_weeks(0), 0)

    def test_hwaseong_two_percent_two_weeks_and_cap(self):
        self.assertEqual(late_delivery_damages(100_000, 14, 0.02, 0.10), 4000.0)
        self.assertEqual(late_delivery_damages(100_000, 100, 0.02, 0.10), 10000.0)

    def test_half_percent_commenced_week_and_cap(self):
        self.assertEqual(late_delivery_damages(100_000, 8, 0.005, 0.05), 1000.0)
        self.assertEqual(late_delivery_damages(100_000, 100, 0.005, 0.05), 5000.0)

    def test_no_damage_before_due(self):
        self.assertEqual(late_delivery_damages(100_000, -1, 0.02, 0.10), 0.0)


if __name__ == "__main__":
    unittest.main()
