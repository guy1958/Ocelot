import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# ocelot_ctl imports udi_interface; use a minimal stand-in when the real package is not installed.
try:
    import udi_interface  # noqa: F401
except ImportError:
    import logging
    stub = types.ModuleType('udi_interface')
    stub.LOGGER = logging.getLogger('udi_stub')
    stub.Node = type('Node', (), {'__init__': lambda self, *a, **k: None})
    stub.Custom = object
    sys.modules['udi_interface'] = stub

import ocelot_ctl as oc
import ocelot_proto as op


class FakeVarNode:
    def __init__(self, log, fail=False):
        self.log = log
        self.fail = fail
        self.quiet_args = []

    def refresh(self, quiet=False):
        self.log.append('vars')
        self.quiet_args.append(quiet)
        if self.fail:
            raise RuntimeError('boom')
        return True


class ShortPollTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self._orig_io = op.get_realtime_io
        self.io_result = bytes(256)

        def fake_io(ser):
            self.log.append('io')
            return self.io_result
        op.get_realtime_io = fake_io

    def tearDown(self):
        op.get_realtime_io = self._orig_io

    def ctrl(self, **kw):
        base = dict(ocelot_ready=True, ser=object(), io_nodes={}, io_fail=0, var_node=FakeVarNode(self.log))
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_reads_io_then_variables(self):
        c = self.ctrl()
        oc.short_poll(c)
        self.assertEqual(self.log, ['io', 'vars'])
        # poll-driven reads are quiet
        self.assertEqual(c.var_node.quiet_args, [True])

    def test_every_short_poll_reads_variables(self):
        c = self.ctrl()
        for _ in range(3):
            oc.short_poll(c)
        self.assertEqual(self.log, ['io', 'vars'] * 3)

    def test_variables_skipped_when_io_read_fails(self):
        self.io_result = None
        c = self.ctrl()
        oc.short_poll(c)
        self.assertEqual(self.log, ['io'])
        self.assertEqual(c.io_fail, 1)

    def test_variables_resume_after_io_recovers(self):
        c = self.ctrl()
        self.io_result = None
        oc.short_poll(c)
        self.io_result = bytes(256)
        oc.short_poll(c)
        self.assertEqual(self.log, ['io', 'io', 'vars'])
        self.assertEqual(c.io_fail, 0)

    def test_nothing_when_not_ready_or_no_port(self):
        oc.short_poll(self.ctrl(ocelot_ready=False))
        oc.short_poll(self.ctrl(ser=None))
        self.assertEqual(self.log, [])

    def test_no_variables_node_is_fine(self):
        oc.short_poll(self.ctrl(var_node=None))
        self.assertEqual(self.log, ['io'])

    def test_variable_refresh_error_does_not_propagate(self):
        c = self.ctrl()
        c.var_node = FakeVarNode(self.log, fail=True)
        oc.short_poll(c)  # must not raise
        self.assertEqual(self.log, ['io', 'vars'])

    def test_plain_poll_does_not_read_variables(self):
        # discover() and query() call poll() and read the variables themselves; poll() must not double up.
        oc.poll(self.ctrl())
        self.assertEqual(self.log, ['io'])


if __name__ == '__main__':
    unittest.main()
