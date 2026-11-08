"""Offline regression checks for temperature input validation and field mapping."""
import unittest
from temperature_service import F, numeric

class TestTemperatureMapping(unittest.TestCase):
    def test_eco_command_targets_programmed_reduction(self):
        self.assertEqual(F["reduction"], (
            "setSetpointLoweringTemperatureInProgMode",
            "io:SetpointLoweringTemperatureInProgModeState"))
    def test_comfort_uses_base_target_not_known_failing_command(self):
        self.assertEqual(F["comfort"], ("setTargetTemperature", "core:TargetTemperatureState"))
    def test_numeric_does_not_accept_bool(self):
        self.assertIsNone(numeric({"x": True}, "x"))
    def test_missing_value_is_not_zero(self):
        self.assertIsNone(numeric({}, "x"))
    def test_valid_number(self):
        self.assertEqual(numeric({"x": 19.5}, "x"), 19.5)

if __name__ == "__main__":
    unittest.main()
