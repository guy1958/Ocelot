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

op.READ_DEADLINE = 0.05

LATCHED_DATA = bytes([1] * 256)
REALTIME_DATA = bytes([2] * 256)


class FakeSer:
    def __init__(self, response=b''):
        self.response = bytearray(response)
        self.written = []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written.append(bytes(data))

    def flush(self):
        pass

    def read(self, n):
        chunk = bytes(self.response[:n])
        del self.response[:n]
        return chunk


class LatchedProtoTests(unittest.TestCase):
    def test_frame_is_the_published_one(self):
        # <200> <50> <0> <0> <0> <0> <0> <250>, from the CPU-XA protocol document
        self.assertEqual(op.FRAME_GET_LATCHED_IO, bytes([200, 50, 0, 0, 0, 0, 0, 250]))
        self.assertEqual(op.FRAME_GET_LATCHED_IO, op.build_frame(op.CMD_GET_LATCHED_IO))
        self.assertEqual(op.CMD_GET_LATCHED_IO, 50)
        self.assertNotEqual(op.FRAME_GET_LATCHED_IO, op.FRAME_GET_REALTIME_IO)

    def test_reply_is_a_3_byte_ack_header_then_256_bytes(self):
        payload = bytes(range(256))
        ser = FakeSer(bytes([6, 0, 6]) + payload)
        self.assertEqual(op.get_latched_io(ser), payload)
        self.assertEqual(ser.written, [op.FRAME_GET_LATCHED_IO])

    def test_trailing_bytes_are_ignored(self):
        payload = bytes(range(256))
        self.assertEqual(op.get_latched_io(FakeSer(bytes([6, 0, 6]) + payload + bytes(2))), payload)

    def test_bad_replies_give_none(self):
        payload = bytes(256)
        # no reply, short reply
        self.assertIsNone(op.get_latched_io(FakeSer(b'')))
        self.assertIsNone(op.get_latched_io(FakeSer(bytes([6, 0, 6]) + bytes(100))))
        # a 42-type style 6-byte header (the real-time layout) is not accepted
        self.assertIsNone(op.get_latched_io(FakeSer(bytes(6) + payload + bytes(2))))
        self.assertIsNone(op.get_latched_io(FakeSer(bytes([6, 0, 7]) + payload)))

    def test_io_source_for_unit(self):
        self.assertEqual(op.io_source_for_unit(op.TYPE_SECU16), op.SOURCE_LATCHED)
        self.assertEqual(op.io_source_for_unit(op.TYPE_SECU16I), op.SOURCE_LATCHED)
        self.assertEqual(op.io_source_for_unit(op.TYPE_RLY08XA), op.SOURCE_REALTIME)
        self.assertIsNone(op.io_source_for_unit(op.TYPE_SECU16IR))
        self.assertIsNone(op.io_source_for_unit(op.TYPE_EMPTY_SLOT))
        self.assertIsNone(op.io_source_for_unit(99))

    def test_every_unit_with_points_has_a_source(self):
        for utype in (op.TYPE_SECU16, op.TYPE_SECU16I, op.TYPE_RLY08XA):
            self.assertTrue(op.points_for_unit(utype))
            self.assertIn(op.io_source_for_unit(utype), (op.SOURCE_LATCHED, op.SOURCE_REALTIME))

    def test_secu16i_layout_matches_the_document(self):
        # document: Data1 = input bits 0-7, Data2 = input bits 8-15
        pts = op.points_for_unit(op.TYPE_SECU16I)
        self.assertEqual([(i, b, bit) for _, i, b, bit in pts], [(i, 0 if i < 8 else 1, i % 8) for i in range(16)])
        data = bytearray(256)
        data[2 * (5 - 1) + 1] = 0b00000010  # unit 5, Data2 bit 1 = input 9
        self.assertEqual([op.get_bit(data, 5, b, bit) for _, _, b, bit in pts][9], 1)
        self.assertEqual(sum(op.get_bit(data, 5, b, bit) for _, _, b, bit in pts), 1)


class FakeNode:
    def __init__(self, log, name, source=None):
        self.log = log
        self.name = name
        if source is not None:
            self.source = source
        self.seen = []

    def update_from(self, data):
        self.log.append(self.name)
        self.seen.append(data)


class FakeVarNode:
    def __init__(self, log):
        self.log = log

    def refresh(self, quiet=False):
        self.log.append('vars')
        return True


class PollSourceTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self._orig_io = op.get_realtime_io
        self._orig_latched = op.get_latched_io
        self.io_result = REALTIME_DATA
        self.latched_result = LATCHED_DATA
        self.latched_raises = False

        def fake_io(ser):
            self.log.append('io')
            return self.io_result

        def fake_latched(ser):
            self.log.append('latched')
            if self.latched_raises:
                raise RuntimeError('link down')
            return self.latched_result

        op.get_realtime_io = fake_io
        op.get_latched_io = fake_latched

    def tearDown(self):
        op.get_realtime_io = self._orig_io
        op.get_latched_io = self._orig_latched

    def ctrl(self, nodes, **kw):
        base = dict(ocelot_ready=True, ser=object(), io_nodes={n.name: n for n in nodes}, io_fail=0,
                    var_node=FakeVarNode(self.log))
        base.update(kw)
        return types.SimpleNamespace(**base)

    def mixed(self):
        return (FakeNode(self.log, 'secu', op.SOURCE_LATCHED), FakeNode(self.log, 'rly', op.SOURCE_REALTIME))

    def test_each_node_gets_data_from_its_own_read(self):
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly])
        oc.poll(c)
        self.assertEqual(secu.seen, [LATCHED_DATA])
        self.assertEqual(rly.seen, [REALTIME_DATA])
        self.assertEqual(self.log, ['latched', 'secu', 'io', 'rly'])
        self.assertEqual(c.io_fail, 0)

    def test_only_latched_nodes_means_only_the_latched_read(self):
        c = self.ctrl([FakeNode(self.log, 'a', op.SOURCE_LATCHED), FakeNode(self.log, 'b', op.SOURCE_LATCHED)])
        oc.poll(c)
        self.assertEqual(self.log, ['latched', 'a', 'b'])

    def test_only_realtime_nodes_means_only_the_realtime_read(self):
        c = self.ctrl([FakeNode(self.log, 'a', op.SOURCE_REALTIME)])
        oc.poll(c)
        self.assertEqual(self.log, ['io', 'a'])

    def test_node_without_a_source_is_read_in_real_time(self):
        c = self.ctrl([FakeNode(self.log, 'a')])
        oc.poll(c)
        self.assertEqual(self.log, ['io', 'a'])

    def test_no_io_nodes_still_makes_one_realtime_read_as_a_link_check(self):
        c = self.ctrl([])
        oc.poll(c)
        self.assertEqual(self.log, ['io'])
        self.io_result = None
        oc.poll(c)
        self.assertEqual(c.io_fail, 1)

    def test_poll_limited_to_latched_makes_no_realtime_read(self):
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly])
        oc.poll(c, sources=(op.SOURCE_LATCHED,))
        self.assertEqual(self.log, ['latched', 'secu'])
        self.assertEqual(rly.seen, [])

    def test_poll_limited_to_a_source_nobody_uses_reads_nothing(self):
        c = self.ctrl([FakeNode(self.log, 'rly', op.SOURCE_REALTIME)])
        oc.poll(c, sources=(op.SOURCE_LATCHED,))
        self.assertEqual(self.log, [])
        self.assertEqual(c.io_fail, 0)
        # and with no I/O nodes there is no liveness read when a source list is given
        oc.poll(self.ctrl([]), sources=(op.SOURCE_LATCHED,))
        self.assertEqual(self.log, [])

    def test_poll_limited_to_realtime_and_latched_keeps_the_fixed_order(self):
        secu, rly = self.mixed()
        oc.poll(self.ctrl([secu, rly]), sources=(op.SOURCE_REALTIME, op.SOURCE_LATCHED))
        self.assertEqual(self.log, ['latched', 'secu', 'io', 'rly'])

    def test_latched_failure_still_updates_realtime_nodes_but_counts_as_failed(self):
        self.latched_result = None
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly])
        oc.poll(c)
        self.assertEqual(self.log, ['latched', 'io', 'rly'])
        self.assertEqual(secu.seen, [])
        self.assertEqual(rly.seen, [REALTIME_DATA])
        self.assertEqual(c.io_fail, 1)

    def test_realtime_failure_still_updates_latched_nodes_but_counts_as_failed(self):
        self.io_result = None
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly])
        oc.poll(c)
        self.assertEqual(self.log, ['latched', 'secu', 'io'])
        self.assertEqual(secu.seen, [LATCHED_DATA])
        self.assertEqual(rly.seen, [])
        self.assertEqual(c.io_fail, 1)

    def test_both_reads_failing_counts_once_per_poll(self):
        self.latched_result = None
        self.io_result = None
        c = self.ctrl(list(self.mixed()))
        oc.poll(c)
        self.assertEqual(c.io_fail, 1)
        oc.poll(c)
        self.assertEqual(c.io_fail, 2)

    def test_failed_count_resets_only_when_every_read_answers(self):
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly], io_fail=2)
        self.latched_result = None
        oc.poll(c)
        self.assertEqual(c.io_fail, 3)
        self.latched_result = LATCHED_DATA
        oc.poll(c)
        self.assertEqual(c.io_fail, 0)

    def test_an_exception_in_a_read_is_a_failed_read_not_a_crash(self):
        self.latched_raises = True
        secu, rly = self.mixed()
        c = self.ctrl([secu, rly])
        oc.poll(c)  # must not raise
        self.assertEqual(c.io_fail, 1)
        self.assertEqual(rly.seen, [REALTIME_DATA])

    def test_nothing_when_not_ready_or_no_port(self):
        secu, rly = self.mixed()
        oc.poll(self.ctrl([secu, rly], ocelot_ready=False))
        oc.poll(self.ctrl([secu, rly], ser=None))
        self.assertEqual(self.log, [])

    def test_short_poll_order_is_latched_then_realtime_then_variables(self):
        c = self.ctrl(list(self.mixed()))
        oc.short_poll(c)
        self.assertEqual(self.log, ['latched', 'secu', 'io', 'rly', 'vars'])

    def test_short_poll_skips_variables_when_the_latched_read_fails(self):
        self.latched_result = None
        c = self.ctrl(list(self.mixed()))
        oc.short_poll(c)
        self.assertNotIn('vars', self.log)

    def test_short_poll_skips_variables_when_the_realtime_read_fails(self):
        self.io_result = None
        c = self.ctrl(list(self.mixed()))
        oc.short_poll(c)
        self.assertNotIn('vars', self.log)


class FakePoly:
    '''Just enough of the Interface for udi_interface.Node.__init__ (no stored driver values).'''

    def db_getNodeDrivers(self, address):
        return []


class NodeSourceTests(unittest.TestCase):
    def test_nodes_remember_their_source_and_default_to_realtime(self):
        r = on.OcelotRelay(FakePoly(), 'ctl', 'a', 'n', None, 1, 0, 1, 0, op.SOURCE_LATCHED)
        i = on.OcelotInput(FakePoly(), 'ctl', 'b', 'n', 1, 0, 0, 0, False, op.SOURCE_LATCHED)
        self.assertEqual((r.source, i.source), (op.SOURCE_LATCHED, op.SOURCE_LATCHED))
        r2 = on.OcelotRelay(FakePoly(), 'ctl', 'a', 'n', None, 3, 0, 0, 0)
        i2 = on.OcelotInput(FakePoly(), 'ctl', 'b', 'n', 3, 0, 0, 0)
        self.assertEqual((r2.source, i2.source), (op.SOURCE_REALTIME, op.SOURCE_REALTIME))


if __name__ == '__main__':
    unittest.main()
