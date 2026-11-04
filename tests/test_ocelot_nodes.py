import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# ocelot_nodes imports udi_interface; use a minimal stand-in when the real package is not installed.
try:
    import udi_interface  # noqa: F401
except ImportError:
    import logging
    stub = types.ModuleType('udi_interface')
    stub.LOGGER = logging.getLogger('udi_stub')
    stub.Node = type('Node', (), {'__init__': lambda self, *a, **k: None})
    stub.Custom = object
    sys.modules['udi_interface'] = stub

import ocelot_nodes as on
import ocelot_proto as op

WRITE_CMD = {'cmd': 'SETVAR', 'query': {'VARNUM.uom107': '10', 'VALUE.uom108': '1234'}}


def reply_with(vnum, value):
    data = bytearray(256)
    data[2 * vnum] = value & 0xFF
    data[2 * vnum + 1] = value >> 8
    return bytes(data)


class WriteThenReadTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.drivers = {}
        self._orig_write = op.write_variable
        self._orig_get = op.get_variables
        self.write_result = True
        self.write_raises = False
        self.read_result = reply_with(10, 1234)

        def fake_write(ser, vnum, value):
            self.log.append(('write', vnum, value))
            if self.write_raises:
                raise RuntimeError('link down')
            return self.write_result

        def fake_get(ser):
            self.log.append('read')
            return self.read_result

        op.write_variable = fake_write
        op.get_variables = fake_get

    def tearDown(self):
        op.write_variable = self._orig_write
        op.get_variables = self._orig_get

    def node(self, ser=True):
        n = on.OcelotVariables.__new__(on.OcelotVariables)
        n.address = 'cpuxavars'
        n.ctrl = types.SimpleNamespace(ser=object() if ser else None)
        n.values = None
        n.read_var = 0
        n.setDriver = lambda driver, value, *a, **k: self.drivers.__setitem__(driver, value)
        return n

    def test_acknowledged_write_is_followed_by_a_read(self):
        n = self.node()
        n.read_var = 10
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [('write', 10, 1234), 'read'])
        self.assertEqual(self.drivers['ST'], 1)
        self.assertEqual(self.drivers['VAR_NUM'], 10)
        self.assertEqual(self.drivers['VAR_VAL'], 1234)
        self.assertEqual(self.drivers['READ_RESULT'], 1)
        # the variable shown in Read Value now reflects what the Ocelot holds
        self.assertEqual(self.drivers['READ_VAL'], 1234)
        self.assertEqual(n.values[10], 1234)

    def test_unacknowledged_write_is_still_followed_by_a_read(self):
        self.write_result = False
        n = self.node()
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [('write', 10, 1234), 'read'])
        self.assertEqual(self.drivers['ST'], 2)
        self.assertEqual(self.drivers['READ_RESULT'], 1)

    def test_failed_read_after_write_keeps_the_write_result(self):
        self.read_result = None
        n = self.node()
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [('write', 10, 1234), 'read'])
        self.assertEqual(self.drivers['ST'], 1)          # the write result is untouched
        self.assertEqual(self.drivers['VAR_VAL'], 1234)
        self.assertEqual(self.drivers['READ_RESULT'], 2)  # No Valid Answer
        self.assertNotIn('READ_VAL', self.drivers)

    def test_no_read_when_the_write_raises(self):
        self.write_raises = True
        n = self.node()
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [('write', 10, 1234)])
        self.assertEqual(self.drivers['ST'], 2)
        self.assertNotIn('READ_RESULT', self.drivers)

    def test_no_write_and_no_read_on_bad_parameters(self):
        n = self.node()
        for bad in ({'query': {'VARNUM': 128, 'VALUE': 1}}, {'query': {'VARNUM': 1}}, {'cmd': 'SETVAR'}, None):
            self.log.clear()
            n.set_var(bad)
            self.assertEqual(self.log, [], str(bad))
            self.assertEqual(self.drivers['ST'], 2)

    def test_no_write_and_no_read_when_port_is_closed(self):
        n = self.node(ser=False)
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [])
        self.assertEqual(self.drivers['ST'], 2)

    def test_each_write_triggers_its_own_read(self):
        n = self.node()
        n.set_var(WRITE_CMD)
        n.set_var(WRITE_CMD)
        self.assertEqual(self.log, [('write', 10, 1234), 'read'] * 2)

    def test_get_and_read_commands_still_read_without_writing(self):
        n = self.node()
        n.get_vars()
        n.read_variable({'query': {'VARNUM.uom107': '10'}})
        self.assertEqual(self.log, ['read', 'read'])
        self.assertEqual(n.read_var, 10)


if __name__ == '__main__':
    unittest.main()
