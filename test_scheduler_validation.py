"""Offline validation tests; never connects to Cozytouch."""
import unittest

from scheduler_service import DAYS, EMPTY, validate_days, build_payload, safe_diff


def week(start="05:00", end="23:00"):
    return {day: [{"start": start, "end": end}, dict(EMPTY), dict(EMPTY)]
            for day in DAYS}


class TestScheduleValidation(unittest.TestCase):
    def test_long_period_and_midnight(self):
        data = week("09:00", "24:00")
        self.assertEqual(validate_days(data), data)

    def test_all_three_periods(self):
        data = week()
        data["monday"] = [
            {"start": "06:00", "end": "08:00"},
            {"start": "12:00", "end": "13:00"},
            {"start": "17:00", "end": "24:00"},
        ]
        self.assertEqual(validate_days(data)["monday"], data["monday"])

    def test_overlapping_rejected(self):
        data = week()
        data["monday"] = [{"start": "05:00", "end": "10:00"},
                          {"start": "09:00", "end": "11:00"}]
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_days(data)

    def test_invalid_midnight_rejected(self):
        data = week("09:00", "24:30")
        with self.assertRaises(ValueError):
            validate_days(data)

    def test_overnight_period_rejected(self):
        data = week("23:00", "02:00")
        with self.assertRaises(ValueError):
            validate_days(data)

    def test_missing_day_rejected(self):
        data = week()
        del data["friday"]
        with self.assertRaises(ValueError):
            validate_days(data)

    def test_nonconsecutive_periods_canonicalized(self):
        data = week()
        data["monday"] = [dict(EMPTY), {"start": "11:00", "end": "16:00"}]
        result = validate_days(data)
        self.assertEqual(result["monday"][0], {"start": "11:00", "end": "16:00"})
        self.assertEqual(result["monday"][1], EMPTY)

    def test_full_payload_preserves_day_order(self):
        original = [{day: week()[day]} for day in reversed(DAYS)]
        wanted = week("09:00", "24:00")
        payload = build_payload(original, wanted)
        self.assertEqual([next(iter(v)) for v in payload], list(reversed(DAYS)))
        self.assertEqual(payload[0]["sunday"][0], {"start": "09:00", "end": "24:00"})

    def test_diff_only_modified_day(self):
        before = week()
        after = week()
        after["monday"][0]["start"] = "09:00"
        changes = safe_diff(before, after)
        self.assertEqual(list(changes), ["monday"])


if __name__ == "__main__":
    unittest.main()
