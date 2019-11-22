"""
Unittests for Generic plugin

"""

__author__ = "Dave Wapstra <dwapstra@cisco.com>"

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import re
import time
import unittest
from unittest.mock import Mock, call, patch

from pyats.datastructures import AttrDict

import unicon
from unicon import Connection
from unicon.mock import mock_device
from unicon.eal.dialogs import Dialog
from unicon.plugins.tests.mock.mock_device_ios import MockDeviceTcpWrapperIOS
from unicon.mock.mock_device import MockDeviceTcpWrapper
from unicon.plugins.generic.statements import login_handler, password_handler
from pyats.topology import loader
from pyats.topology.credentials import Credentials

from unicon.core.errors import (SubCommandFailure, StateMachineError,
    SpawnInitError, CredentialsExhaustedError, UniconAuthenticationError, )


class TestPasswordHandler(unittest.TestCase):

    def setUp(self):
        """ Prepare the mock objects for use with the tests
        """
        self.session = AttrDict()
        self.context = AttrDict({
            'username': 'admin',
            'tacacs_password': 'cisco',
            'enable_password': "admin",
            'line_password': "letmein"
            })

        class MockSpawn:
            pass

        def mock_sendline(*args, **kwargs):
            print("Sendline called with: %s %s" % (args, kwargs))

        self.spawn = MockSpawn()
        self.spawn.buffer = ''
        self.spawn.spawn_command = 'ssh -l cisco@router'
        self.spawn.last_sent = 'ssh -l cisco@router'
        self.spawn.sendline = Mock(side_effect=mock_sendline)
        self.spawn.match = AttrDict()
        self.spawn.match.match_output = ""
        self.spawn.settings = Mock()
        self.spawn.settings.PASSWORD_ATTEMPTS = 3

    def _test_password_handler(self):
        """ Execute password handler twice
        """
        password_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)

    def test_ssh_password_handler_without_tacacs_with_l(self):
        """ Check if password handler detects '-l' and sends tacacs password.
            Send tacacs password only in retry attempt. Should not try enable passwd.
        """
        self.session.tacacs_login = 0
        self.spawn.spawn_command = 'ssh -l admin localhost'
        self.spawn.last_sent = 'ssh -l admin localhost'
        self._test_password_handler()
        self.spawn.sendline.assert_has_calls([call('cisco'), call('cisco')])

    def test_ssh_password_handler_without_tacacs_with_at(self):
        """ Check if password handler detects 'user@host' and sends tacacs password.
            Send tacacs password only in retry attempt. Should not try enable passwd.
        """
        self.session.tacacs_login = 0
        self.spawn.spawn_command = 'ssh admin@localhost'
        self.spawn.last_sent = 'ssh admin@localhost'
        self.spawn.match.match_output = """admin@locahost's password: """
        self._test_password_handler()
        self.spawn.sendline.assert_has_calls([call('cisco'), call('cisco')])

    def test_ssh_password_handler_without_tacacs_without_indicator(self):
        """ If last command is not username and start command does not contain username login
            then send line password.
        """
        self.session.tacacs_login = 0
        self.spawn.spawn_command = 'ssh localhost'
        self.spawn.last_sent = 'ssh localhost'
        self._test_password_handler()
        self.spawn.sendline.assert_has_calls([call('letmein'), call('letmein')])

    def test_non_ssh_password_handler_without_tacacs(self):
        """ Check if line password is sent, for first password prompt.
        """
        self.session.tacacs_login = 0
        self.spawn.spawn_command = 'telnet 127.0.0.1 2001'
        self.spawn.last_sent = 'telnet 127.0.0.1 2001'
        self._test_password_handler()
        self.spawn.sendline.assert_has_calls([call('letmein'), call('letmein')])

    def test_non_ssh_password_handler_with_tacacs(self):
        """ Check if tacacs password is sent if last command sent is username.
        """
        self.session.tacacs_login = 1
        self.spawn.spawn_command = 'telnet 127.0.0.1 2001'
        self.spawn.last_sent = self.context.username
        self._test_password_handler()
        self.spawn.sendline.assert_has_calls([call('cisco'), call('cisco')])

    def test_enable_password(self):
        d = Connection(hostname='Router',
                start=['mock_device_cli --os ios --state console_test_enable'],
                os='ios', enable_password='enpasswd', connection_timeout=15)
        d.connect()

    def test_password_retries(self):
        with self.assertRaises(UniconAuthenticationError):
            for x in range(4):
                password_handler(self.spawn, self.context, self.session)



class TestCredentialLoginPasswordHandlers(unittest.TestCase):

    def setUp(self):
        """ Prepare the mock objects for use with the tests
        """
        self.session = AttrDict()
        self.context = AttrDict({
            'default_cred_name': 'default',
            'credentials': Credentials({
                'default': {'username': 'defun', 'password': 'defpw'},
                'mycred': {'username': 'admin', 'password': 'cisco'},
                'enable': {'password': 'enpasswd'},
            })
        })

        class MockSpawn:
            pass

        def mock_sendline(*args, **kwargs):
            print("Sendline called with: %s %s" % (args, kwargs))

        self.spawn = MockSpawn()
        self.spawn.spawn_command = 'ssh -l cisco@router'
        self.spawn.last_sent = 'ssh -l cisco@router'
        self.spawn.sendline = Mock(side_effect=mock_sendline)
        self.spawn.match = AttrDict()
        self.spawn.match.match_output = ""
        self.spawn.settings = Mock()

    def test_default_cred_sent_if_no_creds_given(self):
        password_handler(self.spawn, self.context, self.session)
        self.spawn.sendline.assert_has_calls([call('defpw')])

    def test_default_cred_sent_if_no_creds_given_with_login(self):
        login_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)
        self.spawn.sendline.assert_has_calls([call('defun'), call('defpw')])

    def test_default_cred_sent_when_unknown_cred_given_with_login(self):
        self.context['cred_list'] = ['badcred']
        login_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)
        self.spawn.sendline.assert_has_calls([call('defun'), call('defpw')])

    def test_unknown_cred_given_with_login(self):
        self.context['cred_list'] = ['badcred']
        self.context['credentials']['default'].pop('username')
        with self.assertRaisesRegex(UniconAuthenticationError,
                '.*No username.*badcred'):
            login_handler(self.spawn, self.context, self.session)
            password_handler(self.spawn, self.context, self.session)

    def test_no_password_specified(self):
        self.context['credentials']['default'].pop('password')
        with self.assertRaisesRegex(UniconAuthenticationError,
                '.*No password.*default'):
            login_handler(self.spawn, self.context, self.session)
            password_handler(self.spawn, self.context, self.session)

    def test_alt_cred_send_login_password(self):
        self.context['cred_list'] = ['mycred']
        login_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)
        self.spawn.sendline.assert_has_calls([call('admin'), call('cisco')])

    def test_cred_seq_login_password(self):
        self.context['cred_list'] = ['mycred', 'default']
        login_handler(self.spawn, self.context, self.session)
        login_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)
        login_handler(self.spawn, self.context, self.session)
        password_handler(self.spawn, self.context, self.session)
        self.spawn.sendline.assert_has_calls(
            [call('admin'), call('cisco'),
             call('defun'), call('defpw')])

    def test_password_failed(self):
        with self.assertRaisesRegex(CredentialsExhaustedError,
                '.*tried without success.*default'):
            login_handler(self.spawn, self.context, self.session)
            password_handler(self.spawn, self.context, self.session)
            password_handler(self.spawn, self.context, self.session)

    def test_enable_password(self):
        d = Connection(hostname='Router',
                start=['mock_device_cli --os ios '\
                    '--state console_test_enable'],
                os='ios', connection_timeout=15,
                credentials=self.context.credentials)
        d.connect()




class TestGenericServices(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state exec'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco',
                            service_attributes=dict(ping=dict(timeout=2468)))
        cls.d.connect()
        cls.md = mock_device.MockDevice(device_os='ios', state='exec')
        cls.ha = MockDeviceTcpWrapperIOS(port=0, state='login,exec_standby')

        # Add command output with 80K lines
        cls.ha.mockdevice.mock_data['enable']['commands']['show ospf dummy'] = \
        "123.123.123.123     123.123.123.123 1000        0x80000003 0x000000 0\n" * 80000

        cls.ha.start()
        cls.ha_device = Connection(hostname='Router',
                                    start=['telnet 127.0.0.1 '+  str(cls.ha.ports[0]), 'telnet 127.0.0.1 '+ str(cls.ha.ports[1]) ],
                                    os='ios', username='cisco', tacacs_password='cisco', enable_password='cisco')
        cls.ha_device.connect()
        cls.logfile_testfile = '/tmp/test_log_file.log'

    @classmethod
    @patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
    @patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
    def tearDownClass(cls):
        cls.d.disconnect()
        cls.ha_device.disconnect()
        cls.ha.stop()
        try:
            os.remove(cls.logfile_testfile)
        except:
            pass

    def test_config_multiple_command_output(self):
        cmd = 'do show version'
        cmd_list = ['do show version', 'do show version']
        ret = self.d.configure(cmd_list)
        test_output =  ret.replace('\r\n', '\n')
        single_cmd_output = cmd + '\n' + self.md.mock_data['exec']['commands']['show version']
        expected_output = single_cmd_output + single_cmd_output
        self.assertEqual(expected_output, test_output)

    def test_config_ha_multiple_command_output(self):
        cmd = 'do show version'
        cmd_list = ['do show version', 'do show version']
        ret = self.ha_device.configure(cmd_list)
        test_output =  ret.replace('\r\n', '\n')
        single_cmd_output = cmd + '\n' + self.md.mock_data['exec']['commands']['show version']
        self.maxDiff = None
        expected_output = single_cmd_output + single_cmd_output
        self.assertEqual(expected_output, test_output)

    def test_log_file(self):
        self.assertIn('/tmp/', self.d.log_file())
        org_file = self.d.logfile
        self.d.log_file(self.logfile_testfile)
        self.d.execute('show version')
        with open(self.logfile_testfile) as fh:
            self.assertIn('show version', fh.read())
        self.d.log_file(org_file)

    def test_sync_state(self):
        try:
            self.ha_device.sync_state()
            result = True
        except Exception as e:
            print('Error in sync_state service: {}'.format(e))
            result = False
        self.assertTrue(result)

    def test_execute_large_output(self):
        self.ha_device.log_user(enable=False)
        # If matching is slow, this command will take longer than 60 seconds
        # (which is the default timeout)
        self.ha_device.execute('show ospf dummy')

    def test_expect_large_output(self):
        self.ha_device.log_user(enable=False)
        # If matching is slow, this command will take longer than 60 seconds
        self.ha_device.sendline('show ospf dummy')
        self.ha_device.expect('^(.*?)#', timeout=60)

    def test_search_size(self):
        self.assertEqual(self.d.spawn.search_size, self.d.settings.SEARCH_SIZE)
        self.d.execute('', search_size=1234)
        self.assertEqual(self.d.spawn.search_size, self.d.settings.SEARCH_SIZE)

    def test_search_size_ha(self):
        self.assertEqual(self.ha_device.active.spawn.search_size, self.ha_device.settings.SEARCH_SIZE)
        self.ha_device.execute('', search_size=1234)
        self.assertEqual(self.ha_device.active.spawn.search_size, self.ha_device.settings.SEARCH_SIZE)

    def test_error_pattern(self):
        with self.assertRaises(SubCommandFailure):
            self.d.execute('unkown command', error_pattern=['^% '])

        with self.assertRaises(SubCommandFailure):
            self.ha_device.execute('unkown command', error_pattern=['^% '])

    def test_multi_thread_execute(self):
        commands = ['show version'] * 3
        with ThreadPoolExecutor(max_workers=3) as executor:
            all_task = [executor.submit(self.d.execute, cmd)
                        for cmd in commands]
            results = [task.result() for task in all_task]

    def test_multi_process_execute(self):
        class Child(multiprocessing.Process):
            pass

        commands = ['show version'] * 3
        processes = [Child(target=self.d.execute, args=(cmd,))
                     for cmd in commands]
        for process in processes:
            process.start()
        for process in processes:
            process.join()

    def test_execute_remove_backspace(self):
        # output with a single backspae
        r = self.d.execute('show command with backspace')
        self.assertEqual(r, 'test')

        # user sending ctrl-u to remove the command, this has multiple backspaces
        self.d.send('abcdef\x15')
        r = self.d.execute('show redundancy sta |  in peer')
        self.assertEqual(r, 'peer state = 8  -STANDBY HOT')

    def test_service_attribute_patching(self):
        self.assertEqual(self.d.ping.timeout, 2468)
        self.assertEqual(self.ha_device.ping.timeout, 60)


class TestConfigureService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = Connection(
            hostname='Router',
            start=['mock_device_cli --os ios --state enable'],
            os='ios',
            username='cisco',
            tacacs_password='cisco',
            enable_password='cisco',
        )
        cls.d.connect()

        cls.ha = MockDeviceTcpWrapperIOS(port=0, state='enable,exec_standby')
        cls.ha.start()
        cls.d_ha = Connection(
            hostname='Router',
            start=['telnet 127.0.0.1 ' + str(cls.ha.ports[0]),
                   'telnet 127.0.0.1 ' + str(cls.ha.ports[1])],
            os='ios',
            username='cisco',
            tacacs_password='cisco',
            enable_password='cisco',
        )
        cls.d_ha.connect()

    def test_config(self):
        out = self.d.configure('no logging console')
        self.assertEqual(out.count('no logging console'), 1)
        out = self.d.configure(['no logging console'] * 3)
        self.assertEqual(out.count('no logging console'), 3)

    def test_ha_config(self):
        out = self.d_ha.configure('no logging console')
        self.assertEqual(out.count('no logging console'), 1)
        out = self.d_ha.configure(['no logging console'] * 3)
        self.assertEqual(out.count('no logging console'), 3)

    def test_bulk_config(self):
        out = self.d.configure('no logging console', bulk=True)
        self.assertEqual(out.count('no logging console'), 1)
        out = self.d.configure(['no logging console'] * 3, bulk=True)
        self.assertEqual(out.count('no logging console'), 3)

        start = time.time()
        out = self.d.configure(['no logging console'] * 3, bulk=True,
                               bulk_chunk_lines=2, bulk_chunk_sleep=4)
        self.assertEqual(out.count('no logging console'), 3)
        stop = time.time()
        self.assertGreater(stop - start, 4)

        self.d.configure.bulk = True
        self.d.configure.bulk_chunk_lines = 2
        self.d.configure.bulk_chunk_sleep = 3
        start = time.time()
        out = self.d.configure(['no logging console'] * 5)
        self.assertEqual(out.count('no logging console'), 5)
        stop = time.time()
        self.assertGreater(stop - start, 6)
        self.d.configure.bulk = False

    def test_ha_bulk_config(self):
        out = self.d_ha.configure('no logging console', bulk=True)
        self.assertEqual(out.count('no logging console'), 1)
        out = self.d_ha.configure(['no logging console'] * 3, bulk=True)
        self.assertEqual(out.count('no logging console'), 3)

        start = time.time()
        out = self.d_ha.configure(['no logging console'] * 3, bulk=True,
                                  bulk_chunk_lines=2, bulk_chunk_sleep=4)
        self.assertEqual(out.count('no logging console'), 3)
        stop = time.time()
        self.assertGreater(stop - start, 4)

        self.d_ha.configure.bulk = True
        self.d_ha.configure.bulk_chunk_lines = 2
        self.d_ha.configure.bulk_chunk_sleep = 3
        start = time.time()
        out = self.d_ha.configure(['no logging console'] * 5)
        self.assertEqual(out.count('no logging console'), 5)
        stop = time.time()
        self.assertGreater(stop - start, 6)
        self.d_ha.configure.bulk = False

    def test_config_lock_retries_succeed(self):
        self.d.execute('set config lock count 2')
        self.d.configure('no logging console',
                         lock_retries=2, lock_retry_sleep=1)
        self.d.configure('no logging console')

    def test_config_lock_retries_fail(self):
        self.d.execute('set config lock count 3')
        with self.assertRaises(SubCommandFailure):
            self.d.configure('no logging console', lock_retries=2)

    def test_ha_config_lock_retries_succeed(self):
        self.d_ha.execute('set config lock count 2')
        self.d_ha.configure('no logging console',
                            lock_retries=2, lock_retry_sleep=1)
        self.d_ha.configure('no logging console')

    def test_ha_config_lock_retries_fail(self):
        self.d_ha.execute('set config lock count 3')
        with self.assertRaises(SubCommandFailure):
            self.d_ha.configure('no logging console', lock_retries=2)

    @classmethod
    @patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
    @patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
    def tearDownClass(cls):
        cls.d.disconnect()
        cls.d_ha.disconnect()
        cls.ha.stop()


class TestExecuteService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state exec'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco')
        cls.d.connect()
        cls.md = mock_device.MockDevice(device_os='ios', state='exec')
        cls.ha = MockDeviceTcpWrapperIOS(port=0, state='login,exec_standby')
        cls.ha.start()
        cls.ha_device = Connection(hostname='Router',
                        start=['telnet 127.0.0.1 '+  str(cls.ha.ports[0]), 'telnet 127.0.0.1 '+ str(cls.ha.ports[1]) ],
                        os='ios', username='cisco', tacacs_password='cisco', enable_password='cisco')
        cls.ha_device.connect()

    @classmethod
    @patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
    @patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
    def tearDownClass(cls):
        cls.d.disconnect()
        cls.ha_device.disconnect()
        cls.ha.stop()

    def setUp(self):
        self.d.enable()
        self.ha_device.enable()
        self.d.settings.EXEC_ALLOW_STATE_CHANGE = False

    def test_universal_execute(self):
        self.d.execute('config term', allow_state_change=True)
        self.assertEqual(self.d.state_machine.current_state, 'config')
        self.d.execute('line console 0')
        self.assertEqual(self.d.state_machine.current_state, 'config')
        self.d.settings.EXEC_ALLOW_STATE_CHANGE = True
        self.d.execute('end')
        self.assertEqual(self.d.state_machine.current_state, 'enable')
        self.d.execute('disable')
        self.assertEqual(self.d.state_machine.current_state, 'disable')
        self.d.execute('enable', reply=Dialog([[r'^(.*?)Password:', 'sendline_ctx(tacacs_password)', None, False, False]]))
        self.assertEqual(self.d.state_machine.current_state, 'enable')
        self.d.execute('disable')
        self.assertEqual(self.d.state_machine.current_state, 'disable')
        self.ha_device.execute('config term', allow_state_change=True)
        self.assertEqual(self.ha_device.active.state_machine.current_state, 'config')

    def test_execute_allow_state_change(self):
        with self.assertRaises(StateMachineError) as e1:
            self.d.execute('config term')
        self.assertEqual(self.d.state_machine.current_state, 'config')
        self.ha_device.settings.EXEC_ALLOW_STATE_CHANGE = True
        with self.assertRaises(StateMachineError) as e2:
            self.ha_device.execute('config term', allow_state_change=False)
        self.assertEqual(self.ha_device.active.state_machine.current_state, 'config')

    def test_execute_with_more_backspace(self):
        self.d.settings.MORE_CONTINUE = '\r'
        output = self.d.execute('show command with more backspace')
        self.assertEqual(output, 'first\r\n\r\nsecond\r\n\r\nthird')
        self.assertEqual(repr(output), repr('first\r\n\r\nsecond\r\n\r\nthird'))

    def test_execute_with_escape_more_backspace(self):
        self.d.settings.MORE_CONTINUE = '\r'
        output = self.d.execute('show command with escape more backspace')
        self.assertEqual(output, 'first\r\n\r\nsecond\r\n\r\nthird')
        self.assertEqual(repr(output), repr('first\r\n\r\nsecond\r\n\r\nthird'))

    def test_execute_with_escape_more(self):
        self.d.settings.MORE_CONTINUE = '\r'
        output = self.d.execute('show command with escape more')
        self.assertEqual(output, 'first\r\n\r\nsecond\r\n\r\nthird')
        self.assertEqual(repr(output), repr('first\r\n\r\nsecond\r\n\r\nthird'))

    def test_execute_with_more(self):
        self.d.settings.MORE_CONTINUE = '\r'
        output = self.d.execute('show command with more')
        self.assertEqual(output, 'first\r\n\r\nsecond\r\n\r\nthird')
        self.assertEqual(repr(output), repr('first\r\n\r\nsecond\r\n\r\nthird'))

    def test_execute_with_transient_match_1(self):
        output = self.d.execute('show command with transient match',
                                matched_retries=3,
                                matched_retry_sleep=7)
        self.assertEqual(output, 'head\r\nRouter#\r\ntail')

    def test_execute_with_transient_match_2(self):
        self.d.execute.matched_retry_sleep = 20
        try:
            output = self.d.execute('show command with transient match')
            self.assertEqual(output, 'head\r\nRouter#\r\ntail')
        finally:
            self.d.execute.matched_retry_sleep = \
                self.d.settings.EXECUTE_MATCHED_RETRY_SLEEP


class TestTransmitReceive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = Connection(
            hostname='Router',
            start=['mock_device_cli --os ios --state exec'],
            os='ios', enable_password='cisco',
            username='cisco',
            tacacs_password='cisco'
        )
        cls.d.connect()
        cls.term_buffer_pattern = re.compile(r'term width 0.*#', re.S)

    @classmethod
    @patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
    @patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
    def tearDownClass(cls):
        cls.d.disconnect()

    def test_transmit(self):
        self.assertTrue(self.d.transmit('term width 0\r'))

    def test_receive_when_match(self):
        self.d.send('term width 0\r')
        self.assertTrue(self.d.receive(r'.*#'))
        self.assertRegex(self.d.receive_buffer(), self.term_buffer_pattern)

    def test_receive_buffer(self):
        self.d.sendline('term width 0')
        self.d.receive(r'^.*#')
        self.assertRegex(self.d.receive_buffer(), self.term_buffer_pattern)

    def test_receive_nopattern(self):
        self.d.transmit('term width 0\r')
        self.assertFalse(self.d.receive(r'nopattern^', timeout=10))
        self.assertRegex(self.d.receive_buffer(), self.term_buffer_pattern)

    def test_receive_no_match(self):
        self.d.transmit('term width 0\r')
        self.assertFalse(self.d.receive(r'somepattern', timeout=10))
        self.assertEqual(self.d.receive_buffer(), '')

    def test_receive_after_receive_no_match(self):
        self.d.sendline('term width 0')
        self.assertFalse(self.d.receive(r'wrongpattern', timeout=10))
        self.assertEqual(self.d.receive_buffer(), '')
        self.assertTrue(self.d.receive(r'term width 0.*#', timeout=10))
        self.assertRegex(self.d.receive_buffer(), self.term_buffer_pattern)

    def test_receive_nopattern_after_receive_no_match(self):
        self.d.sendline('term width 0')
        self.assertFalse(self.d.receive(r'wrongpattern', timeout=10))
        self.assertEqual(self.d.receive_buffer(), '')
        self.assertFalse(self.d.receive(r'nopattern^', timeout=10))
        self.assertRegex(self.d.receive_buffer(), self.term_buffer_pattern)


class TestEscapeHandler(unittest.TestCase):

    def setUp(self):
        self.old_term_setting = os.environ.get('TERM')
        os.environ['TERM'] = 'VT100'

    def test_escape_handler_uav(self):
        c = Connection(hostname='Router',
                       start=['mock_device_cli --os ios --state ios_connect_console_server_with_uav'],
                       os='ios', line_password="cisco",
                       username='cisco',
                       tacacs_password='cisco',
                       enable_password='cisco')
        r = c.connect()
        last_lines = "\n".join(r.splitlines()[-4:])
        self.assertEqual(last_lines, '\nUser Access Verification\nPassword: cisco\nRouter>')

    def test_escape_handler_username(self):
        c = Connection(hostname='Router',
                       start=['mock_device_cli --os ios --state ios_connect_console_server_with_username'],
                       os='ios', line_password="cisco",
                       username='cisco',
                       tacacs_password='cisco',
                       enable_password='cisco')
        r = c.connect()
        last_lines = "\n".join(r.splitlines()[-4:])
        self.assertEqual(last_lines, '#######################\nusername: cisco\nPassword: cisco\nRouter>')

    def test_escape_handler_password(self):
        c = Connection(hostname='Router',
                       start=['mock_device_cli --os ios --state ios_connect_console_server_with_password'],
                       os='ios', line_password="cisco",
                       username='cisco',
                       tacacs_password='cisco',
                       enable_password='cisco')
        r = c.connect()
        expected_pattern = re.compile(
            ".*" + re.escape("Escape character is '^]'.\r\npassword: cisco\r\nRouter>"),
            re.DOTALL)
        self.assertRegex(r, expected_pattern)


    def tearDown(self):
        if self.old_term_setting:
            os.environ['TERM'] = self.old_term_setting
        else:
            os.environ.pop('TERM')

@patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
@patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
class TestLearnHostname(unittest.TestCase):

    def test_learn_hostname_default(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state exec'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco',
                            learn_hostname=True)
        c.settings.TERM='vt100'
        c.connect()
        md = mock_device.MockDevice(device_os='ios', state='exec')
        expected_output = md.mock_data['exec']['commands']['show version'].rstrip()
        output = c.execute('show version').replace('\r', '')
        self.assertEqual(output, expected_output)

    def test_learn_hostname_r1(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state exec --hostname R1'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco',
                            learn_hostname=True)
        c.settings.TERM='vt100'
        c.connect()
        self.assertEqual(c.hostname, 'R1')
        md = mock_device.MockDevice(device_os='ios', state='exec')
        expected_output = md.mock_data['exec']['commands']['show version'].rstrip()
        output = c.execute('show version').replace('\r', '')
        self.assertEqual(output, expected_output)

    def test_learn_default_hostname(self):
        d = Connection(hostname='X',
                            start=['mock_device_cli --os ios --state enable --hostname Switch'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco',
                            learn_hostname=True)
        d.settings.TERM='vt100'
        d.connect()
        self.assertEqual(d.hostname, 'Switch')
        d.disconnect()

    def test_learn_hostname_hash_characters(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state execHashCharacters'],
                            os='ios', enable_password='cisco',
                            username='cisco',
                            tacacs_password='cisco',
                            learn_hostname=True)
        c.settings.TERM='vt100'
        c.connect()
        self.assertNotIn('#',c.hostname)
        c.disconnect()

class TestLargeConfigOnXR(unittest.TestCase):

    def test_exception(self):
        d = Connection(hostname='Router', start=['mock_device_cli --os iosxr --state enable'], os='iosxr')
        d.connect()
        with self.assertRaises(StateMachineError):
            d.configure('large config', timeout=2)
        d.disconnect()

    def test_config_timeout(self):
        d = Connection(hostname='Router', start=['mock_device_cli --os iosxr --state enable'], os='iosxr')
        d.connect()
        d.configure('large config', timeout=20)
        d.disconnect()

class TestConnect(unittest.TestCase):

    def test_connect_start_cmd_not_present(self):
        d = Connection(hostname='Router', start=['xtelnetx 127.0.0.1'], os='ios')
        with self.assertRaises(SpawnInitError):
            d.connect()

    def test_connect_with_setup(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state ios_setup'],
                            os='ios',
                            username='cisco',
                            enable_password='cisco',
                            tacacs_password='cisco',
                            init_exec_commands=[],
                            init_config_commands=[])
        c.connect()
        self.assertEqual(c.state_machine.current_state, 'enable')


    def test_connect_with_setup_mgmt(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os ios --state enable'],
                            os='ios',
                            username='cisco',
                            enable_password='cisco',
                            tacacs_password='cisco',
                            # init_exec_commands=[],
                            init_config_commands=[]
                            )
        c.connect()
        c.sendline('setup_mgmt')
        c.connection_provider.connect()
        self.assertEqual(c.state_machine.current_state, 'enable')

    def test_connect_serial_console(self):
        c = Connection(hostname='Router',
                            start=['mock_device_cli --os iosxr --state connect_serial'],
                            os='iosxr',
                            username='admin',
                            enable_password='admin',
                            tacacs_password='admin',
                            init_config_commands=[]
                            )
        c.connect()

    def test_multi_thread_connect(self):
        dev_dic = {
            'os': 'ios',
            'hostname': 'Router',
            'start': ['mock_device_cli --os ios --state login'],
            'username': 'cisco',
            'tacacs_password': 'cisco',
            'enable_password': 'cisco'
        }
        with ThreadPoolExecutor(max_workers=3) as executor:
            all_task = [executor.submit(Connection(**dev_dic).connect)
                        for _ in range(3)]
            results = [task.result() for task in all_task]


class TestClearLinePasswords(unittest.TestCase):
    def setUp(self):
        from unicon.utils import Utils
        self.utils = Utils()

    def test_clear_line_username_password(self):
         md = MockDeviceTcpWrapper(device_os='ios', port=0, state='ts_login', vty=True)
         md.start()
         term_server = "127.0.0.1 " + str(md.ports[0])
         self.utils.clear_line(term_server, 35, 'admin', 'lab', 'cisco')
         md.stop()

    def test_clear_line_enable_password(self):
         md = MockDeviceTcpWrapper(device_os='ios', port=0, state='console_test_enable', vty=True)
         md.start()
         term_server = "127.0.0.1 " + str(md.ports[0])
         self.utils.clear_line(term_server, 35, 'admin', 'lab', 'enpasswd')
         md.stop()


@patch.object(unicon.settings.Settings, 'POST_DISCONNECT_WAIT_SEC', 0)
@patch.object(unicon.settings.Settings, 'GRACEFUL_DISCONNECT_WAIT_SEC', 0.2)
class TestTacacsLoginPasswordPrompt(unittest.TestCase):

    def test_connect_with_custom_auth_prompt(self):
        d = Connection(hostname='Router', start=['mock_device_cli --os ios --state custom_login'],
                         username='cisco', tacacs_password='cisco', os='ios', enable_password='cisco')
        d.settings.LOGIN_PROMPT = r'Identifier:'
        d.settings.PASSWORD_PROMPT = r'Passe:'
        d.connect()
        d.disconnect()

    def test_topology_connect_with_custom_auth_prompt(self):
        md = MockDeviceTcpWrapper(device_os='ios',port=0, state='custom_login')
        md.start()
        template_testbed = """
        devices:
          Router:
            os: ios
            type: router
            tacacs:
              username: cisco
              login_prompt: 'Identifier:'
              password_prompt: 'Passe:'
            passwords:
              tacacs: cisco
              enable: cisco
            connections:
              defaults:
                class: unicon.Unicon
              a:
                protocol: telnet
                ip: 127.0.0.1
                port: {}
        """.format(md.ports[0])
        t = loader.load(template_testbed)
        d = t.devices['Router']
        d.connect()
        d.disconnect()
        md.stop()

    def test_ha_connect_with_custom_auth_prompt(self):
        d = Connection(hostname='Router', start=['mock_device_cli --os ios --state custom_login,exec_standby'],
                         username='cisco', tacacs_password='cisco', os='ios', enable_password='cisco')
        d.settings.LOGIN_PROMPT = r'Identifier:'
        d.settings.PASSWORD_PROMPT = r'Passe:'
        d.connect()
        d.disconnect()

    def test_topology_ha_connect_with_custom_auth_prompt(self):
        md = MockDeviceTcpWrapper(device_os='ios',port=0, state='custom_login,exec_standby')
        md.start()
        template_testbed = """
        devices:
          Router:
            os: ios
            type: router
            tacacs:
              username: cisco
              login_prompt: 'Identifier:'
              password_prompt: 'Passe:'
            passwords:
              tacacs: cisco
              enable: cisco
            connections:
              defaults:
                class: unicon.Unicon
              a:
                protocol: telnet
                ip: 127.0.0.1
                port: {}
              b:
                protocol: telnet
                ip: 127.0.0.1
                port: {}
        """.format(md.ports[0], md.ports[1])
        t = loader.load(template_testbed)
        d = t.devices['Router']
        d.connect()
        d.disconnect()
        md.stop()

if __name__ == "__main__":
    unittest.main()