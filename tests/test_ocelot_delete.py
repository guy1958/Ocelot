import os
import sys
import time
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


class FakeNotices:
    def __init__(self):
        self.items = {}

    def __setitem__(self, key, value):
        self.items[key] = value

    def delete(self, key):
        self.items.pop(key, None)


class FakePoly:
    '''Just enough of the Interface for discover(), delete_modules() and udi_interface.Node.

    on_add, when set, is called with the address of every node added (to simulate PG3 confirming it).
    events records the order of adds, confirmations (written by the test) and deletes.'''

    ADDNODEDONE = 5

    def __init__(self):
        self.added = []
        self.deleted = []
        self.sent = []
        self.events = []
        self.subscriptions = []
        self.subscribe_raises = False
        self.on_add = None
        self.Notices = FakeNotices()
        self.fail_on = set()

    def db_getNodeDrivers(self, address):
        return []

    def getValidAddress(self, name):
        return name.lower()[:14]

    def getValidName(self, name):
        return name

    def getNodeNameFromDb(self, address):
        return None

    def addNode(self, node, **kwargs):
        self.added.append(node)
        self.events.append(('add', node.address))
        if self.on_add:
            self.on_add(node.address)

    def delNode(self, address):
        if address in self.fail_on:
            raise RuntimeError('cannot delete %s' % address)
        self.deleted.append(address)
        self.events.append(('del', address))

    def subscribe(self, topic, callback, address=None):
        if self.subscribe_raises:
            raise RuntimeError('cannot subscribe')
        self.subscriptions.append((topic, callback))

    def send(self, message, kind):
        self.sent.append((message, kind))


class FakeVarNode:
    def refresh(self, quiet=False):
        return True

    def reportDrivers(self):
        pass


class FakeResident:
    address = 'residentir'

    def reportDrivers(self):
        pass


def unit_type_reply(types_by_unit):
    data = bytearray([254] * 256)
    for unit, utype in types_by_unit.items():
        data[unit - 1] = utype
    return bytes(data)


# unit 1 = SECU-16 (16 points), unit 2 = RLY08-XA (8 relays), unit 3 = SECU-16IR (16 zones), unit 4 = unsupported type 20
MODULES = {1: 11, 2: 13, 3: 6, 4: 20}
MODULE_NODE_COUNT = 16 + 8 + 16 + 1


class DeleteTestBase(unittest.TestCase):
    def setUp(self):
        self.reply = unit_type_reply({})
        self.realtime_reads = 0
        self._orig = (op.get_unit_types, op.get_latched_io, op.get_realtime_io)
        self._orig_step = oc.ADD_WAIT_STEP
        oc.ADD_WAIT_STEP = 0.01
        op.get_unit_types = lambda ser: self.reply
        op.get_latched_io = lambda ser: bytes(256)

        def realtime(ser):
            self.realtime_reads += 1
            return bytes(256)
        op.get_realtime_io = realtime
        self.poly = FakePoly()
        self.resident = FakeResident()
        self.var_node = FakeVarNode()
        self.ctrl = types.SimpleNamespace(
            poly=self.poly, address='ctl', ser=object(), ser_key='socket://192.168.0.70:3001',
            ocelot_params={'IPAddress': '192.168.0.70', 'IPPort': '3001'}, io_nodes={}, ir_nodes={},
            placeholder_nodes={}, resident_ir=self.resident, var_node=self.var_node, io_fail=0, persist_dir=None,
            reportDrivers=lambda: None)
        self.auto_ack(True)

    def tearDown(self):
        op.get_unit_types, op.get_latched_io, op.get_realtime_io = self._orig
        oc.ADD_WAIT_STEP = self._orig_step

    def auto_ack(self, on):
        '''PG3 confirms every node add at once (on) or never, until the test confirms them itself (off).'''
        self.poly.on_add = self.ack if on else None

    def ack(self, address):
        self.poly.events.append(('ack', address))
        oc.add_done(self.ctrl, {'address': address})

    def discover_with(self, types_by_unit):
        self.reply = unit_type_reply(types_by_unit)
        oc.discover(self.ctrl)

    def module_addresses(self):
        c = self.ctrl
        return set(c.io_nodes) | set(c.ir_nodes) | set(c.placeholder_nodes)

    def run_delete(self, wait=5.0):
        thread = oc.delete_modules(self.ctrl, wait)
        self.assertIsNotNone(thread)
        thread.join(10)
        self.assertFalse(thread.is_alive())


class DeleteModuleNodesTests(DeleteTestBase):
    def test_every_module_node_is_deleted(self):
        self.discover_with(MODULES)
        expected = self.module_addresses()
        self.assertEqual(len(expected), MODULE_NODE_COUNT)
        self.run_delete()
        self.assertEqual(set(self.poly.deleted), expected)
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)  # none twice

    def test_each_kind_of_module_node_is_included(self):
        self.discover_with(MODULES)
        self.run_delete()
        deleted = set(self.poly.deleted)
        self.assertIn('u1r0', deleted)    # SECU-16 relay
        self.assertIn('u1i0', deleted)    # SECU-16 input
        self.assertIn('u2r7', deleted)    # RLY08-XA relay
        self.assertIn('u3z15', deleted)   # SECU-16IR zone
        self.assertIn('u4t20', deleted)   # placeholder

    def test_controller_resident_ir_and_variables_are_kept(self):
        self.discover_with(MODULES)
        self.run_delete()
        self.assertNotIn('ctl', self.poly.deleted)
        self.assertNotIn('residentir', self.poly.deleted)
        self.assertNotIn('cpuxavars', self.poly.deleted)
        self.assertIs(self.ctrl.resident_ir, self.resident)
        self.assertIs(self.ctrl.var_node, self.var_node)

    def test_registries_are_emptied_in_place(self):
        io, ir, ph = self.ctrl.io_nodes, self.ctrl.ir_nodes, self.ctrl.placeholder_nodes
        self.discover_with(MODULES)
        self.run_delete()
        self.assertEqual((self.ctrl.io_nodes, self.ctrl.ir_nodes, self.ctrl.placeholder_nodes), ({}, {}, {}))
        self.assertIs(self.ctrl.io_nodes, io)
        self.assertIs(self.ctrl.ir_nodes, ir)
        self.assertIs(self.ctrl.placeholder_nodes, ph)

    def test_nothing_is_sent_to_the_ocelot(self):
        self.discover_with(MODULES)
        before = self.realtime_reads
        calls = []
        original = op.send_command
        op.send_command = lambda ser, frame: calls.append(frame) or True
        try:
            self.run_delete()
        finally:
            op.send_command = original
        self.assertEqual(calls, [])
        self.assertEqual(self.realtime_reads, before)

    def test_discover_creates_the_module_nodes_again(self):
        self.discover_with(MODULES)
        first_added = len(self.poly.added)
        self.run_delete()
        self.discover_with(MODULES)
        self.assertEqual(len(self.module_addresses()), MODULE_NODE_COUNT)
        self.assertEqual(len(self.poly.added) - first_added, MODULE_NODE_COUNT)  # resident IR / variables not re-added
        self.assertIs(self.ctrl.resident_ir, self.resident)

    def test_one_node_that_cannot_be_deleted_does_not_stop_the_rest(self):
        self.discover_with(MODULES)
        self.poly.fail_on = {'u1r3'}
        self.run_delete()  # must not raise
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT - 1)
        self.assertNotIn('u1r3', self.poly.deleted)
        self.assertEqual(self.module_addresses(), set())

    def test_every_delete_failing_still_finishes(self):
        self.discover_with(MODULES)
        self.poly.fail_on = self.module_addresses()
        self.run_delete()  # must not raise
        self.assertEqual(self.poly.deleted, [])
        self.assertEqual(self.module_addresses(), set())
        self.assertFalse(self.ctrl.delete_running)

    def test_nothing_to_delete_does_nothing(self):
        self.run_delete()
        self.assertEqual(self.poly.deleted, [])

    def test_calling_it_twice_deletes_each_node_once(self):
        self.discover_with(MODULES)
        self.run_delete()
        self.run_delete()
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)

    def test_missing_registries_are_tolerated(self):
        bare = types.SimpleNamespace(poly=self.poly)
        thread = oc.delete_modules(bare, 1.0)
        thread.join(10)  # must not raise
        self.assertEqual(self.poly.deleted, [])

    def test_short_poll_afterwards_only_makes_the_link_check(self):
        self.discover_with(MODULES)
        self.run_delete()
        before = self.realtime_reads
        oc.short_poll(self.ctrl)  # must not raise
        self.assertEqual(self.realtime_reads - before, 1)
        self.assertEqual(self.ctrl.io_fail, 0)

    def test_query_afterwards_still_works(self):
        self.discover_with(MODULES)
        self.run_delete()
        oc.query(self.ctrl)  # must not raise

    def test_can_be_pressed_again_after_it_finished(self):
        self.discover_with(MODULES)
        self.run_delete()
        self.assertFalse(self.ctrl.delete_running)
        self.discover_with(MODULES)
        self.run_delete()
        self.assertEqual(len(self.poly.deleted), 2 * MODULE_NODE_COUNT)


class PendingAddTests(DeleteTestBase):
    '''The 1.16.1 fix: PG3 confirms node adds slowly, and a node removed before its add is confirmed is
    created anyway afterwards (the 1.16.0 log). The delete must wait for the confirmations.'''

    def test_every_module_node_add_is_tracked_until_confirmed(self):
        self.auto_ack(False)
        self.discover_with(MODULES)
        self.assertEqual(self.ctrl.pending_adds, self.module_addresses())
        self.assertEqual(len(self.ctrl.pending_adds), MODULE_NODE_COUNT)
        for addr in sorted(self.ctrl.pending_adds):
            self.ack(addr)
        self.assertEqual(self.ctrl.pending_adds, set())

    def test_resident_ir_and_variables_are_not_tracked(self):
        # they are not module nodes; discover() adds them directly and the delete never waits for them
        self.auto_ack(False)
        self.ctrl.resident_ir = None
        self.ctrl.var_node = None
        self.discover_with({1: 11})
        self.assertNotIn('residentir', self.ctrl.pending_adds)
        self.assertNotIn('cpuxavars', self.ctrl.pending_adds)
        self.assertIn('residentir', [n.address for n in self.poly.added])

    def test_delete_waits_for_pending_adds_then_deletes_everything(self):
        self.auto_ack(False)
        self.discover_with(MODULES)
        pending = set(self.ctrl.pending_adds)
        thread = oc.delete_modules(self.ctrl, 30.0)
        time.sleep(0.2)
        self.assertTrue(thread.is_alive())
        self.assertEqual(self.poly.deleted, [])  # nothing is removed while adds are still queued
        for addr in sorted(pending):
            self.ack(addr)
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(set(self.poly.deleted), pending)
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)
        kinds = [e[0] for e in self.poly.events]
        last_ack = max(i for i, k in enumerate(kinds) if k == 'ack')
        first_del = min(i for i, k in enumerate(kinds) if k == 'del')
        self.assertLess(last_ack, first_del)  # every confirmation came before the first removal

    def test_confirmations_trickling_in_keep_it_waiting(self):
        # the 1.16.0 situation: the delete was pressed while PG3 was still confirming adds
        self.auto_ack(False)
        self.discover_with(MODULES)
        addresses = sorted(self.ctrl.pending_adds)
        half = len(addresses) // 2
        thread = oc.delete_modules(self.ctrl, 30.0)
        for addr in addresses[:half]:
            self.ack(addr)
        time.sleep(0.2)
        self.assertTrue(thread.is_alive())
        self.assertEqual(self.poly.deleted, [])
        for addr in addresses[half:]:
            self.ack(addr)
        thread.join(10)
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)
        self.assertEqual(self.module_addresses(), set())

    def test_gives_up_waiting_after_the_timeout_and_deletes_anyway(self):
        self.auto_ack(False)
        self.discover_with(MODULES)
        thread = oc.delete_modules(self.ctrl, 0.2)
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)
        self.assertEqual(self.ctrl.pending_adds, set())
        self.assertFalse(self.ctrl.delete_running)

    def test_a_second_press_while_one_is_running_is_ignored(self):
        self.auto_ack(False)
        self.discover_with(MODULES)
        pending = sorted(self.ctrl.pending_adds)
        first = oc.delete_modules(self.ctrl, 30.0)
        self.assertIsNotNone(first)
        self.assertIsNone(oc.delete_modules(self.ctrl, 30.0))
        self.assertTrue(self.ctrl.delete_running)
        for addr in pending:
            self.ack(addr)
        first.join(10)
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)  # each node deleted once
        self.assertFalse(self.ctrl.delete_running)

    def test_with_tracking_off_it_does_not_wait(self):
        self.auto_ack(False)
        self.ctrl.add_tracking = False
        self.discover_with(MODULES)
        thread = oc.delete_modules(self.ctrl, 30.0)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.poly.deleted), MODULE_NODE_COUNT)

    def test_a_failed_add_is_not_left_pending(self):
        node = types.SimpleNamespace(address='u9r0')

        def boom(n, **kw):
            raise RuntimeError('no')
        self.poly.addNode = boom
        with self.assertRaises(RuntimeError):
            oc._add_node(self.ctrl, node)
        self.assertNotIn('u9r0', getattr(self.ctrl, 'pending_adds', set()))

    def test_add_done_ignores_anything_unexpected(self):
        self.ctrl.pending_adds = {'a'}
        for data in (None, {}, 'a', 5, {'address': None}, {'address': 'zzz'}, {'id': 'a'}):
            oc.add_done(self.ctrl, data)
        self.assertEqual(self.ctrl.pending_adds, {'a'})
        oc.add_done(self.ctrl, {'address': 'a', 'id': 'a', 'success': True})
        self.assertEqual(self.ctrl.pending_adds, set())

    def test_deleting_clears_the_deleted_addresses_from_pending(self):
        self.auto_ack(False)
        self.discover_with({4: 20})
        self.assertEqual(self.ctrl.pending_adds, {'u4t20'})
        oc._delete_module_nodes(self.ctrl)
        self.assertEqual(self.ctrl.pending_adds, set())


class SubscribeTests(DeleteTestBase):
    def test_subscribes_once_to_the_add_done_event_and_clears_pending(self):
        oc._subscribe_add_done(self.ctrl)
        self.assertEqual(len(self.poly.subscriptions), 1)
        self.assertEqual(self.poly.subscriptions[0][0], FakePoly.ADDNODEDONE)
        self.assertIsNot(self.ctrl.add_tracking, False)
        self.ctrl.pending_adds = {'x'}
        self.poly.subscriptions[0][1]({'address': 'x'})
        self.assertEqual(self.ctrl.pending_adds, set())
        oc._subscribe_add_done(self.ctrl)
        self.assertEqual(len(self.poly.subscriptions), 1)

    def test_a_failed_subscription_turns_tracking_off(self):
        self.poly.subscribe_raises = True
        oc._subscribe_add_done(self.ctrl)  # must not raise
        self.assertIs(self.ctrl.add_tracking, False)

    def test_start_sets_up_tracking_before_discovering(self):
        ctrl = types.SimpleNamespace(poly=self.poly, address='ctl')
        oc.start(ctrl)  # no connection settings, so discover() stops at its notice
        self.assertEqual(ctrl.pending_adds, set())
        self.assertFalse(ctrl.delete_running)
        self.assertEqual(len(self.poly.subscriptions), 1)
        self.assertIn('config', self.poly.Notices.items)


class DeleteCommandWiringTests(unittest.TestCase):
    def test_profile_declares_the_command_on_the_controller(self):
        import json
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profile.json')
        with open(path, encoding='utf-8') as fh:
            profile = json.load(fh)
        controller = [n for n in profile['nodedefs'] if n['id'] == 'controller'][0]
        accepted = {c['id']: c for c in controller['cmds']['accepts']}
        self.assertIn('DELMODULES', accepted)
        self.assertEqual(accepted['DELMODULES']['name'], 'Delete Module Nodes')
        self.assertEqual(accepted['DELMODULES']['native'], 'false')
        self.assertNotIn('parameters', accepted['DELMODULES'])


if __name__ == '__main__':
    unittest.main()
