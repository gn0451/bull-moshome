"""Offline unit tests for family-scoped device refresh."""

import unittest
from unittest.mock import MagicMock

from bull_iot.client import BullCloudClient, Device


class RefreshDevicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = BullCloudClient()
        self.client.get_families = MagicMock(
            return_value=[{"familyId": 1}, {"familyId": 2}]
        )
        self.client.switch_family = MagicMock()
        self.client.get_rooms_and_devices = MagicMock(return_value=[])

    def tearDown(self) -> None:
        self.client.close()

    def test_explicit_family_does_not_enumerate_all_families(self) -> None:
        devices = {}
        self.client.refresh_devices(devices, [2])

        self.client.get_families.assert_not_called()
        self.client.switch_family.assert_called_once_with(2)

    def test_default_keeps_cli_all_family_behavior(self) -> None:
        self.client.refresh_devices({}, None)

        self.assertEqual(
            [call.args[0] for call in self.client.switch_family.call_args_list],
            [1, 2],
        )

    def test_successful_refresh_prunes_removed_devices(self) -> None:
        devices = {
            "removed": Device(iot_id="removed", product_id=4),
        }
        self.client.refresh_devices(devices, [1])

        self.assertEqual(devices, {})


if __name__ == "__main__":
    unittest.main()
