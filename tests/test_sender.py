from unittest import TestCase, skip, skipIf
from unittest.mock import patch, call, mock_open
from zabbix.sender import ZabbixMetric, ZabbixSender

import json
import os
import re
import struct
import sys


class ZabbixMetricTests(TestCase):
    def test_metrics_init(self):
        zm = ZabbixMetric('host1', 'key1', 100500, 1457358608)
        self.assertEqual(zm.host, 'host1')
        self.assertEqual(zm.key, 'key1')
        self.assertEqual(zm.clock, 1457358608)

    def test_metrics_init_auto_time(self):
        zm = ZabbixMetric('host1', 'key1', 100500)
        self.assertEqual(zm.host, 'host1')
        self.assertEqual(zm.key, 'key1')
        self.assertEqual(len(re.search('^(\d*)$', zm.clock).groups()), 1)

    def test_metrics_repr(self):
        zm = ZabbixMetric('host1', 'key1', 100500)
        zm_repr = json.loads(zm.__repr__())
        self.assertEqual(zm_repr, zm.__dict__)


class TestsZabbixSender(TestCase):
    def setUp(self):
        self.resp_header = b'ZBXD\x01\\\x00\x00\x00\x00\x00\x00\x00'
        self.resp_body = b'''{"response":"success","info":"processed: 0; \
failed: 10; total: 10; seconds spent: 0.000078"}
'''

    def test_ZS_init(self):
        zs = ZabbixSender()
        self.assertEqual(zs.__class__.__name__, 'ZabbixSender')
        self.assertEqual(isinstance(zs.zabbix_uri[0], tuple), True)
        self.assertEqual(zs.zabbix_uri[0][0], '127.0.0.1')
        self.assertEqual(zs.zabbix_uri[0][1], 10051)

    def test_ZS_init_config(self):
        folder = os.path.dirname(__file__)
        filename = os.path.join(folder, 'data/zabbix_agentd.conf')
        zs = ZabbixSender(use_config=filename)
        self.assertEqual(zs.__class__.__name__, 'ZabbixSender')
        self.assertEqual(isinstance(zs.zabbix_uri[0], tuple), True)
        self.assertEqual(zs.zabbix_uri[0][0], '192.168.1.2')
        self.assertEqual(zs.zabbix_uri[0][1], 10051)

    def test_ZS_init_config_exception(self):
        folder = os.path.dirname(__file__)
        filename = os.path.join(folder, 'zabbix_agent.conf')
        with self.assertRaises(Exception):
            zs = ZabbixSender(use_config=filename)

    @skipIf(sys.version_info.minor != 5, reason="Worked only 3.5")
    def test_ZS_init_config_default(self):
        folder = os.path.dirname(__file__)
        filename = os.path.join(folder, 'data/zabbix_agentd.conf')
        file = open(filename, 'r')
        f = file.read()
        with patch('zabbix.sender.open', mock_open(read_data=f)):
            zs = ZabbixSender(use_config=True)
            self.assertEqual(zs.zabbix_uri, [('192.168.1.2', 10051)])
        file.close()

    def test_ZS_repr(self):
        zs = ZabbixSender()
        self.assertEqual(zs.__repr__(), json.dumps(zs.__dict__))

    def test_ZS_load_from_config(self):
        folder = os.path.dirname(__file__)
        filename = os.path.join(folder, 'data/zabbix_agentd.conf')
        zs = ZabbixSender()
        result = zs._load_from_config(config_file=filename)
        self.assertEqual(result, [('192.168.1.2', 10051)])

    def test_ZS_create_messages(self):
        m = [ZabbixMetric('host1', 'key1', 1),
             ZabbixMetric('host2', 'key2', 2)]
        zs = ZabbixSender()
        result = zs._create_messages(m)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_ZS_create_request(self):
        message = [
            '{"clock": "1457445366", "host": "host1",\
            "value": "1", "key": "key1"}',
            '{"clock": "1457445366", "host": "host2",\
            "value": "2", "key": "key2"}']
        zs = ZabbixSender()
        result = zs._create_request(message)
        self.assertIsInstance(result, bytes)
        result = json.loads(result.decode())
        self.assertEqual(result['request'], 'sender data')
        self.assertEqual(len(result['data']), 2)

    def test_ZS_create_request_failed(self):
        message = [
            '{"clock": "1457445366", "host: \
            "host1", "value": "1", "key": "key1"}',
            '{"clock": "1457445366", "host": \
            "host2", "value": "2", "key": "key2"}']
        zs = ZabbixSender()
        result = zs._create_request(message)
        with self.assertRaises(Exception):
            result = json.loads(result.decode())

    def test_ZS_create_packet(self):
        message = [
            '{"clock": "1457445366", "host": "host1",\
            "value": "1", "key": "key1"}',
            '{"clock": "1457445366", "host": "host2",\
            "value": "2", "key": "key2"}']
        zs = ZabbixSender()
        request = zs._create_request(message)
        result = zs._create_packet(request)
        data_len = struct.pack('<Q', len(request))
        self.assertEqual(result[5:13], data_len)
        self.assertEqual(result[:13],
                         b'ZBXD\x01\xc4\x00\x00\x00\x00\x00\x00\x00')

    @patch('zabbix.sender.socket.socket', autospec=True)
    @skip('Issue: #27 [https://github.com/blacked/py-zabbix/issues/27]')
    def test_ZS_recive(self, mock_socket):
        mock_data = b'\x01\\\x00\x00\x00\x00\x00\x00\x00'
        mock_socket.recv.side_effect = (False, b'ZBXD', mock_data)

        zs = ZabbixSender()
        result = zs._receive(mock_socket, 13)
        self.assertEqual(result, b'ZBXD' + mock_data)
        self.assertEqual(mock_socket.recv.call_count, 3)
        mock_socket.recv.assert_has_calls([call(13), call(13), call(9)])

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_get_response(self, mock_socket):
        mock_socket.recv.side_effect = (self.resp_header, self.resp_body)

        zs = ZabbixSender()
        result = zs._get_response(mock_socket)
        mock_socket.recv.assert_has_calls([call(92)])
        self.assertEqual(result['response'], 'success')

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_get_response_fail(self, mock_socket):
        mock_socket.recv.side_effect = (b'IDDQD', self.resp_body)

        zs = ZabbixSender()
        result = zs._get_response(mock_socket)
        self.assertFalse(result)

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_get_response_fail_s_close(self, mock_socket):
        mock_socket.recv.side_effect = (b'IDDQD', self.resp_body)
        mock_socket.close.side_effect = Exception

        zs = ZabbixSender()
        result = zs._get_response(mock_socket)
        self.assertFalse(result)

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_send(self, mock_socket):
        mock_data = b'\x01\\\x00\x00\x00\x00\x00\x00\x00'
        mock_socket.return_value = mock_socket
        mock_socket.recv.side_effect = (b'ZBXD', mock_data, self.resp_body)

        zm = ZabbixMetric('host1', 'key1', 100500, 1457358608)
        zs = ZabbixSender()
        result = zs.send([zm])
        self.assertTrue(result)

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_send_sendall_exception(self, mock_socket):
        mock_socket.return_value = mock_socket
        mock_socket.sendall.side_effect = Exception

        zm = ZabbixMetric('host1', 'key1', 100500, 1457358608)
        zs = ZabbixSender()
        with self.assertRaises(Exception):
            zs.send([zm])

    @patch('zabbix.sender.socket.socket', autospec=True)
    def test_ZS_send_failed(self, mock_socket):
        mock_data = b'\x01\\\x00\x00\x00\x00\x00\x00\x00'
        mock_socket.return_value = mock_socket
        mock_socket.recv.side_effect = (b'ZBXD', mock_data, b'''
{"response": "suces","info":"processed: 0; failed: \
10; total: 10; seconds spent: 0.000078"}
''')

        zm = ZabbixMetric('host1', 'key1', 100500, 1457358608)
        zs = ZabbixSender()
        with self.assertRaises(Exception):
            zs.send([zm])
