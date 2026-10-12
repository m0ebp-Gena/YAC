import unittest
from unittest.mock import Mock
from modules.connection_watch import ConnectionWatch, reconnect_same_radio


class ConnectionWatchTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.radio = Mock(is_dummy=False, port='original')
        self.read = Mock(return_value='7.159')
        self.say = Mock()
        self.reconnect = Mock(return_value=True)
        self.watch = ConnectionWatch(self.radio, self.read, self.say, self.reconnect,
                                     clock=lambda: self.now)

    def tick(self):
        self.now += 5
        self.watch.tick()

    def test_idle_queries_are_read_only_and_silent(self):
        self.watch.tick()
        self.read.assert_not_called()
        for _ in range(720):
            self.tick()
        self.assertEqual(self.read.call_count, 720)
        self.assertEqual(self.watch.frequency, '7.159')
        self.say.assert_not_called()
        self.reconnect.assert_not_called()
        self.radio.close.assert_not_called()

    def test_three_failures_then_single_notice_and_recovery(self):
        self.read.return_value = None
        self.tick()
        self.tick()
        self.say.assert_not_called()
        self.tick()
        self.assertTrue(self.watch.lost)
        self.say.assert_called_once_with('lost')
        self.reconnect.return_value = False
        self.tick()
        self.say.assert_called_once_with('lost')
        self.reconnect.return_value = True
        self.read.return_value = '14.2'
        self.tick()
        self.assertFalse(self.watch.lost)
        self.assertEqual(self.say.call_args.args, ('restored',))
        self.assertFalse(self.radio.is_dummy)

    def test_dummy_never_polled(self):
        self.radio.is_dummy = True
        self.tick()
        self.read.assert_not_called()

    def test_exception_after_reopen_closes_failed_handle(self):
        self.watch.lost = True
        self.read.side_effect = OSError('unplugged')
        self.tick()
        self.radio.close.assert_called_once()
        self.assertTrue(self.watch.lost)
        self.say.assert_not_called()

    def test_recovery_only_probes_matching_usb_identity(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        radio = SimpleNamespace(usb_identity='10C4:0001:ABC', port='old', baudrate=38400,
                                protocol='CAT', model_id='ID0670', civ_address=None)
        port = SimpleNamespace(device='new', vid=0x10C4, pid=1, serial_number='ABC')
        other = SimpleNamespace(device='old', vid=0x10C4, pid=1, serial_number='OTHER')
        replacement = SimpleNamespace(serial=object(), port='new', port_details={})
        with patch('serial.tools.list_ports.comports', return_value=[other, port]), \
             patch('modules.find_rad._probe_saved_profiles', return_value=[replacement]) as probe:
            self.assertTrue(reconnect_same_radio(radio))
        self.assertEqual(probe.call_args.args[1], [port])
        self.assertEqual(probe.call_args.args[0][0]['model_id'], 'ID0670')
        self.assertEqual(radio.port, 'new')
