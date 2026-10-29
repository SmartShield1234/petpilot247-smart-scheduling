import unittest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from pavi_verified_appointment_adapter import verified_appointment_from_row, AppointmentEvidenceUnavailable

BASE = dict(appointment_id='a1', location_id='l1', calendar_id='c1', assigned_user_id='g1',
            start_time='2026-11-02T14:00:00Z', end_time='2026-11-02T15:00:00Z',
            date_updated='2026-10-28T14:00:00Z', is_deleted=0)
EVENT = dict(id='a1', locationId='l1', calendarId='c1', assignedUserId='g1',
             startTime=BASE['start_time'],endTime=BASE['end_time'],dateUpdated=BASE['date_updated'])
ADDR = dict(location_id='l1', appointment_id='a1',revision=BASE['date_updated'],
            service_address='123 Example St', confirmed=True, source_authenticated=True)

class VerifiedAppointmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_matching_evidence(self):
        obj = await verified_appointment_from_row(BASE, detail_reader=AsyncMock(return_value=EVENT),
                        address_authority=AsyncMock(return_value=ADDR))
        self.assertEqual(obj.address, '123 Example St')
        self.assertEqual(obj.appointment_id, 'a1')

    async def test_unconfirmed_address_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row(BASE, detail_reader=AsyncMock(return_value=EVENT),
                        address_authority=AsyncMock(return_value={**ADDR, 'confirmed':False}))

    async def test_stale_address_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row(BASE, detail_reader=AsyncMock(return_value=EVENT),
                        address_authority=AsyncMock(return_value={**ADDR, 'revision':'2026-10-27T14:00:00Z'}))

    async def test_ghl_staff_mismatch_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row(BASE, detail_reader=AsyncMock(return_value={**EVENT, 'assignedUserId':'wrong'}),
                        address_authority=AsyncMock(return_value=ADDR))

    async def test_ghl_revision_mismatch_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row(BASE, detail_reader=AsyncMock(return_value={**EVENT, 'dateUpdated':'2026-10-27T14:00:00Z'}),
                        address_authority=AsyncMock(return_value=ADDR))

    async def test_deleted_appointment_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row({**BASE,'is_deleted':True}, detail_reader=AsyncMock(return_value=EVENT),
                        address_authority=AsyncMock(return_value=ADDR))

    async def test_missing_resolver_rejected(self):
        with self.assertRaises(AppointmentEvidenceUnavailable):
            await verified_appointment_from_row(BASE,address_authority=None)

if __name__=='__main__': unittest.main()
