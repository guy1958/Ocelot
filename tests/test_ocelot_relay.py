import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# ocelot_nodes / ocelot_ctl import udi_interface; use a minimal stand-in when the real package is not installed.
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
import ocelot_nodes as on
import ocelot_proto as op


class FakeNode:
    def __init__(self, log, name, source):
        self.log = log
        self.name = name
        self.source = source
        self.seen = []

    def update_from(self, data):
        self.log.append(self.name)
        self.seen.append(data)


class RelayThenReadTests(unittest.TestCase):
    '''After a relay On/Off the plugin makes only the Get Latched I/O read (1.13.0), never Get Real Time I/O.

    Since 1.15.0 the commanded relay keeps the state just sent to IoX (forced), and that read leaves it alone.'''

    def setUp(self):
        self.log = []
        self.drivers = {}
        self.set_calls = []
        self._orig = (op.write_relay, op.get_realtime_io, op.get_latched_io)
        self.write_result = True
        self.write_raises = False
        self.latched_result = bytes(256)

        def fake_write(ser, unit, relay, on):
            self.log.append(('write', unit, relay, on))
            if self.write_raises:
                raise RuntimeError('link down')
            return self.write_result

        def fake_latched(ser):
            self.log.append('latched')
            return self.latched_result

        def fake_realtime(ser):
            self.log.append('io')
            return bytes(256)

        op.write_relay = fake_write
        op.get_latched_io = fake_latched
        op.get_realtime_io = fake_realtime

    def tearDown(self):
        op.write_relay, op.get_realtime_io, op.get_latched_io = self._orig

    def ctrl(self, ser=True, ready=True, nodes=None):
        if nodes is None:
            nodes = [FakeNode(self.log, 'in1', op.SOURCE_LATCHED)]
        return types.SimpleNamespace(ocelot_ready=ready, ser=object() if ser else None, io_fail=0,
                                     io_nodes={n.name: n for n in nodes})

    def set_driver(self, driver, value, *a, **k):
        self.drivers[driver] = value
        self.set_calls.append((driver, value, k.get('force', False)))

    def relay(self, ctrl, source=op.SOURCE_REALTIME, register=False):
        r = on.OcelotRelay.__new__(on.OcelotRelay)
        r.address = 'u3r7'
        r.ctrl = ctrl
        r.unit, r.relay, r.byte, r.bit, r.source = 3, 7, 0, 7, source
        r.setDriver = self.set_driver
        if register:
            ctrl.io_nodes['u3r7'] = r
        return r

    def secu_relay(self, ctrl):
        '''A SECU-16 relay node as discover() makes it: latched source, listed in io_nodes.'''
        r = self.relay(ctrl, op.SOURCE_LATCHED, register=True)
        r.unit, r.relay, r.byte, r.bit = 2, 7, 1, 7  # unit 2, relay 7: Data2 bit 7
        r.address = 'u2r7'
        return r

    def test_on_is_followed_by_a_latched_read_that_updates_the_inputs(self):
        c = self.ctrl()
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True), 'latched', 'in1'])
        self.assertEqual(self.drivers['ST'], 1)
        self.assertEqual(c.io_nodes['in1'].seen, [bytes(256)])

    def test_off_is_followed_by_a_latched_read(self):
        c = self.ctrl()
        self.relay(c).dof()
        self.assertEqual(self.log, [('write', 3, 7, False), 'latched', 'in1'])
        self.assertEqual(self.drivers['ST'], 0)

    def test_no_realtime_read_after_a_relay_command_even_with_realtime_nodes(self):
        secu = FakeNode(self.log, 'secu', op.SOURCE_LATCHED)
        rly = FakeNode(self.log, 'rly', op.SOURCE_REALTIME)
        c = self.ctrl(nodes=[secu, rly])
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True), 'latched', 'secu'])
        self.assertNotIn('io', self.log)
        self.assertEqual(rly.seen, [])  # RLY08-XA nodes wait for the next regular poll

    def test_rly08xa_relay_keeps_the_commanded_state_after_the_command(self):
        secu = FakeNode(self.log, 'secu', op.SOURCE_LATCHED)
        rly = FakeNode(self.log, 'rly', op.SOURCE_REALTIME)
        c = self.ctrl(nodes=[secu, rly])
        self.relay(c, op.SOURCE_REALTIME).don()
        self.assertEqual(self.drivers['ST'], 1)

    def test_no_read_at_all_when_there_are_no_latched_nodes(self):
        c = self.ctrl(nodes=[FakeNode(self.log, 'rly', op.SOURCE_REALTIME)])
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True)])
        self.assertEqual(self.drivers['ST'], 1)

    def test_no_read_when_there_are_no_io_nodes(self):
        c = self.ctrl(nodes=[])
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True)])

    def test_unacknowledged_command_still_reads(self):
        self.write_result = False
        c = self.ctrl()
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True), 'latched', 'in1'])
        self.assertNotIn('ST', self.drivers)  # the plugin does not claim a state it could not confirm

    def test_no_read_when_the_write_raises(self):
        self.write_raises = True
        c = self.ctrl()
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True)])

    def test_nothing_when_the_port_is_closed(self):
        c = self.ctrl(ser=False)
        self.relay(c).don()
        self.assertEqual(self.log, [])

    def test_failed_latched_read_keeps_the_command_result(self):
        self.latched_result = None
        c = self.ctrl()
        self.relay(c).don()
        self.assertEqual(self.log, [('write', 3, 7, True), 'latched'])
        self.assertEqual(self.drivers['ST'], 1)
        self.assertEqual(c.io_fail, 1)

    def test_error_in_the_read_never_propagates(self):
        orig = oc.poll
        try:
            def boom(ctrl, sources=None, skip=None):
                raise RuntimeError('boom')
            oc.poll = boom
            c = self.ctrl()
            self.relay(c).don()  # must not raise
            self.assertEqual(self.drivers['ST'], 1)
        finally:
            oc.poll = orig

    def test_each_command_reads_once(self):
        c = self.ctrl()
        r = self.relay(c)
        r.don()
        r.dof()
        self.assertEqual(self.log.count('latched'), 2)
        self.assertEqual(self.log.count('io'), 0)

    def test_relay_asks_for_the_latched_source_only_and_to_be_left_alone(self):
        asked = []
        orig = oc.poll
        try:
            oc.poll = lambda ctrl, sources=None, skip=None: asked.append((sources, skip))
            r = self.relay(self.ctrl())
            r.don()
        finally:
            oc.poll = orig
        self.assertEqual(asked, [((op.SOURCE_LATCHED,), (r,))])

    def test_unacknowledged_command_does_not_ask_for_the_relay_to_be_left_alone(self):
        self.write_result = False
        asked = []
        orig = oc.poll
        try:
            oc.poll = lambda ctrl, sources=None, skip=None: asked.append((sources, skip))
            self.relay(self.ctrl()).don()
        finally:
            oc.poll = orig
        self.assertEqual(asked, [((op.SOURCE_LATCHED,), None)])

    # ---- 1.15.0: the commanded status is sent at once and the read that follows must not undo it ----

    def test_commanded_state_is_sent_with_force(self):
        c = self.ctrl()
        self.relay(c).don()
        self.assertEqual(self.set_calls[0], ('ST', 1, True))
        self.relay(c).dof()
        self.assertEqual(self.set_calls[1], ('ST', 0, True))

    def test_status_is_sent_before_the_read_is_made(self):
        c = self.ctrl()
        order = []
        r = self.relay(c)
        r.setDriver = lambda driver, value, *a, **k: order.append(('set', value))
        orig = op.get_latched_io
        op.get_latched_io = lambda ser: order.append('latched') or bytes(256)
        try:
            r.don()
        finally:
            op.get_latched_io = orig
        self.assertEqual(order, [('set', 1), 'latched'])

    def test_stale_latched_off_does_not_undo_an_acknowledged_on(self):
        # The 1.14.0 log: On was sent, then the very next latched read still showed Off.
        c = self.ctrl(nodes=[FakeNode(self.log, 'in1', op.SOURCE_LATCHED)])
        r = self.secu_relay(c)
        self.latched_result = bytes(256)  # relay bit reads 0
        r.don()
        self.assertEqual(self.drivers['ST'], 1)
        self.assertEqual([call for call in self.set_calls if call[0] == 'ST'], [('ST', 1, True)])
        self.assertEqual(self.log, [('write', 2, 7, True), 'latched', 'in1'])

    def test_stale_latched_on_does_not_undo_an_acknowledged_off(self):
        c = self.ctrl(nodes=[FakeNode(self.log, 'in1', op.SOURCE_LATCHED)])
        r = self.secu_relay(c)
        stale = bytearray(256)
        stale[2 * (2 - 1) + 1] = 0b10000000  # unit 2, Data2 bit 7 still latched On
        self.latched_result = bytes(stale)
        r.dof()
        self.assertEqual(self.drivers['ST'], 0)
        self.assertEqual([call for call in self.set_calls if call[0] == 'ST'], [('ST', 0, True)])

    def test_the_read_still_updates_the_other_nodes_after_an_acknowledged_command(self):
        other = types.SimpleNamespace(name='other', source=op.SOURCE_LATCHED, seen=[])
        other.update_from = lambda data: other.seen.append(data)
        c = self.ctrl(nodes=[other])
        r = self.secu_relay(c)
        r.don()
        self.assertEqual(other.seen, [bytes(256)])

    def test_a_later_regular_poll_updates_the_relay_again(self):
        c = self.ctrl(nodes=[])
        r = self.secu_relay(c)
        r.don()
        self.assertEqual(self.drivers['ST'], 1)
        c.ocelot_ready = True
        oc.poll(c)  # a regular poll: nothing is skipped, the Ocelot's reported state (0 here) is shown
        self.assertEqual(self.drivers['ST'], 0)

    def test_an_unacknowledged_command_lets_the_read_update_the_relay(self):
        self.write_result = False
        c = self.ctrl(nodes=[])
        r = self.secu_relay(c)
        stale = bytearray(256)
        stale[2 * (2 - 1) + 1] = 0b10000000
        self.latched_result = bytes(stale)
        r.don()
        self.assertEqual(self.drivers['ST'], 1)  # from the read, not claimed by the command
        self.assertEqual([call for call in self.set_calls if call[0] == 'ST'], [('ST', 1, False)])

    def test_only_the_commanded_relay_is_left_alone(self):
        c = self.ctrl(nodes=[])
        r = self.secu_relay(c)
        sibling = on.OcelotRelay.__new__(on.OcelotRelay)
        sibling.address, sibling.ctrl, sibling.source = 'u2r6', c, op.SOURCE_LATCHED
        sibling.unit, sibling.relay, sibling.byte, sibling.bit = 2, 6, 1, 6
        sibling_calls = []
        sibling.setDriver = lambda driver, value, *a, **k: sibling_calls.append((driver, value))
        c.io_nodes['u2r6'] = sibling
        r.don()
        self.assertEqual(sibling_calls, [('ST', 0)])  # refreshed from the read


class PollSkipTests(unittest.TestCase):
    def setUp(self):
        self._orig = (op.get_realtime_io, op.get_latched_io)
        op.get_latched_io = lambda ser: bytes(256)
        op.get_realtime_io = lambda ser: bytes(256)

    def tearDown(self):
        op.get_realtime_io, op.get_latched_io = self._orig

    def test_skipped_node_is_not_updated_but_the_read_still_counts(self):
        seen = []
        a = types.SimpleNamespace(source=op.SOURCE_LATCHED, update_from=lambda d: seen.append('a'))
        b = types.SimpleNamespace(source=op.SOURCE_LATCHED, update_from=lambda d: seen.append('b'))
        c = types.SimpleNamespace(ocelot_ready=True, ser=object(), io_fail=2, io_nodes={'a': a, 'b': b})
        oc.poll(c, sources=(op.SOURCE_LATCHED,), skip=(a,))
        self.assertEqual(seen, ['b'])
        self.assertEqual(c.io_fail, 0)

    def test_skip_defaults_to_nothing(self):
        seen = []
        a = types.SimpleNamespace(source=op.SOURCE_LATCHED, update_from=lambda d: seen.append('a'))
        c = types.SimpleNamespace(ocelot_ready=True, ser=object(), io_fail=0, io_nodes={'a': a})
        oc.poll(c)
        self.assertEqual(seen, ['a'])


if __name__ == '__main__':
    unittest.main()
