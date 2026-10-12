"""Driver hints describe observed metadata, never installation status."""
import unittest
from types import SimpleNamespace
from modules import find_rad


class DriverDiagnostics(unittest.TestCase):
    def test_usb_vendor_or_descriptions_supply_evidence(self):
        for properties in ({'vid': 0x10C4}, {'description': 'CP2102 USB bridge'},
                           {'manufacturer': 'Silicon Laboratories'},
                           {'product': 'Silicon Labs interface'}):
            with self.subTest(properties=properties):
                port = SimpleNamespace(device='COM3', **properties)
                details = find_rad._diagnostic_port_details(port)
                self.assertIs(details['silicon_labs_metadata_seen'], True)
                self.assertTrue(details['silicon_labs_evidence'])
                self.assertTrue(find_rad._is_icom_candidate(port, False))

    def test_missing_or_other_manufacturer_is_false(self):
        for properties in ({}, {'vid': 0x0403, 'manufacturer': 'FTDI'},
                           {'description': 'USB Serial Port'}):
            details = find_rad._diagnostic_port_details(SimpleNamespace(device='COM3', **properties))
            self.assertIs(details['silicon_labs_metadata_seen'], False)
            self.assertEqual(details['silicon_labs_evidence'], [])

    def test_log_reports_aggregate_and_per_port_with_gentle_hint(self):
        for ports in ([], [SimpleNamespace(device='COM3', description='USB Serial Port')]):
            with self.assertLogs('yac', level='INFO') as captured:
                find_rad._log_port_diagnostics(ports)
            output = '\n'.join(captured.output)
            self.assertIn('silicon_labs_metadata_seen=false', output)
            self.assertIn('this does not mean the driver is missing', output)
            self.assertIn('External CI-V interfaces', output)
        ports = [SimpleNamespace(device='COM3', vid=0x10C4), SimpleNamespace(device='COM4')]
        with self.assertLogs('yac', level='INFO') as captured:
            find_rad._log_port_diagnostics(ports)
        output = '\n'.join(captured.output)
        self.assertIn('silicon_labs_metadata_seen=true', output)
        self.assertIn('"silicon_labs_metadata_seen": false', output)
        self.assertIn('"silicon_labs_metadata_seen": true', output)
        self.assertNotIn('check the manufacturer', output)


if __name__ == '__main__':
    unittest.main()
