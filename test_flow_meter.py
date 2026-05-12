import unittest

from flow_meter_gui import FlowStats


class FlowStatsTest(unittest.TestCase):
    def test_total_and_remaining_litres_are_calculated_from_pulses(self):
        stats = FlowStats(pulses_per_litre=10, tank_litres=100)

        for _ in range(125):
            stats.add_pulse(timestamp=1.0)

        self.assertEqual(stats.total_litres_used(), 12.5)
        self.assertEqual(stats.tank_litres_remaining(), 87.5)
        self.assertEqual(stats.tank_percent_remaining(), 87.5)

    def test_rolling_window_volume_uses_recent_pulses_only(self):
        stats = FlowStats(pulses_per_litre=10, tank_litres=100)

        for _ in range(10):
            stats.add_pulse(timestamp=1.0)
        for _ in range(20):
            stats.add_pulse(timestamp=95.0)

        self.assertEqual(stats.litres_in_window(60, now=100.0), 2.0)
        self.assertEqual(stats.litres_in_window(120, now=100.0), 3.0)

    def test_reset_clears_used_volume_and_history(self):
        stats = FlowStats(pulses_per_litre=10, tank_litres=100)

        stats.add_pulse(timestamp=1.0)
        stats.reset_used_volume()

        self.assertEqual(stats.total_litres_used(), 0.0)
        self.assertEqual(stats.litres_in_window(60, now=2.0), 0.0)
        self.assertEqual(stats.tank_litres_remaining(), 100.0)

    def test_invalid_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            FlowStats(pulses_per_litre=0, tank_litres=100)
        with self.assertRaises(ValueError):
            FlowStats(pulses_per_litre=10, tank_litres=-1)


if __name__ == "__main__":
    unittest.main()
