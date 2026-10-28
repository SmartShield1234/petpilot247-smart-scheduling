import unittest
from datetime import datetime, timedelta, timezone
from pavi_postgres_snapshot_reader import validate_appointment_rows, SnapshotEvidenceError

IDS = [f'calendar-{i}' for i in range(11)]
NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
ROW = ('location-1', 'appointment-1', IDS[0], 'groomer-1', 'confirmed',
       NOW, NOW + timedelta(hours=1), NOW, False)

class SnapshotReaderTests(unittest.TestCase):
    def test_valid_row_extracts_untrusted_metadata(self):
        rows = validate_appointment_rows([ROW], expected_calendar_ids=IDS, location_id='location-1')
        self.assertEqual(rows[0]['groomer_id'], 'groomer-1')
        self.assertNotIn('address', rows[0])
    def test_missing_groomer_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW[:3]+(None,)+ROW[4:]], expected_calendar_ids=IDS, location_id='location-1')
    def test_mismatched_location_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW], expected_calendar_ids=IDS, location_id='other-location')
    def test_unknown_calendar_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW[:2]+('unknown',)+ROW[3:]], expected_calendar_ids=IDS, location_id='location-1')
    def test_duplicate_appointment_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW, ROW], expected_calendar_ids=IDS, location_id='location-1')
    def test_naive_time_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW[:5]+(NOW.replace(tzinfo=None),)+ROW[6:]], expected_calendar_ids=IDS, location_id='location-1')
    def test_invalid_duration_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW[:6]+(NOW,)+ROW[7:]], expected_calendar_ids=IDS, location_id='location-1')
    def test_insufficient_calendar_config_rejected(self):
        with self.assertRaises(SnapshotEvidenceError):
            validate_appointment_rows([ROW], expected_calendar_ids=IDS[:4], location_id='location-1')

if __name__ == '__main__':
    unittest.main()
