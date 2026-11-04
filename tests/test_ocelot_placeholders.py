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


class FakeNotices:
    def __init__(self):
        self.items = {}

    def __setitem__(self, key, value):
        self.items[key] = value

    def delete(self, key):
        self.items.pop(key, None)


class FakePoly:
    '''Just enough of the Interface for discover() and udi_interface.Node.'''

    def __init__(self):
        self.added = []
        self.deleted = []
        self.sent = []
        self.Notices = FakeNotices()

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

    def delNode(self, address):
        self.deleted.append(address)

    def send(self, message, kind):
        self.sent.append((message, kind))


class FakeVarNode:
    def refresh(self, quiet=False):
        return True

    def reportDrivers(self):
        pass


class FakeNode:
    '''Stands in for the resident IR node, which discover() leaves alone when one is already set.'''

    def reportDrivers(self):
        pass


def unit_type_reply(types_by_unit):
    '''256 bytes as Get Unit Type returns them: the given units, every other slot 254 (empty).'''
    data = bytearray([254] * 256)
    for unit, utype in types_by_unit.items():
        data[unit - 1] = utype
    return bytes(data)


class DiscoverPlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.reply = unit_type_reply({})
        self._orig = (op.get_unit_types, op.get_latched_io, op.get_realtime_io)
        op.get_unit_types = lambda ser: self.reply
        op.get_latched_io = lambda ser: bytes(256)
        op.get_realtime_io = lambda ser: bytes(256)
        self.poly = FakePoly()
        self.ctrl = types.SimpleNamespace(
            poly=self.poly, address='ctl', ser=object(), ser_key='socket://192.168.0.70:3001',
            ocelot_params={'IPAddress': '192.168.0.70', 'IPPort': '3001'}, io_nodes={}, ir_nodes={},
            placeholder_nodes={}, resident_ir=FakeNode(), var_node=FakeVarNode(), io_fail=0, persist_dir=None,
            reportDrivers=lambda: None)

    def tearDown(self):
        op.get_unit_types, op.get_latched_io, op.get_realtime_io = self._orig

    def discover_with(self, types_by_unit):
        self.reply = unit_type_reply(types_by_unit)
        oc.discover(self.ctrl)

    def placeholders(self):
        return [n for n in self.poly.added if isinstance(n, on.OcelotPlaceholder)]

    def test_unsupported_type_gets_a_placeholder_named_mod_unit_type_n(self):
        self.discover_with({5: 20})
        (node,) = self.placeholders()
        self.assertEqual(node.name, 'Mod 5 Type 20')
        self.assertEqual(node.address, 'u5t20')
        self.assertEqual(node.primary, 'ctl')
        self.assertEqual(node.unit, 5)
        self.assertEqual(node.unit_type, 20)

    def test_placeholder_shows_the_type_code_and_has_no_commands(self):
        self.discover_with({5: 20})
        (node,) = self.placeholders()
        self.assertEqual(node.id, 'placeholder')
        self.assertEqual(node.getDriver('ST'), 20)
        self.assertEqual(node.commands, {})
        self.assertEqual(on.OcelotPlaceholder.commands, {})
        self.assertEqual([d['driver'] for d in node.drivers], ['ST'])

    def test_one_placeholder_per_unsupported_module(self):
        self.discover_with({2: 7, 3: 20, 9: 20, 128: 255})
        names = sorted(n.name for n in self.placeholders())
        self.assertEqual(names, sorted(['Mod 2 Type 7', 'Mod 3 Type 20', 'Mod 9 Type 20', 'Mod 128 Type 255']))
        self.assertEqual(len({n.address for n in self.placeholders()}), 4)

    def test_supported_types_get_no_placeholder(self):
        self.discover_with({1: 11, 2: 12, 3: 13})
        self.assertEqual(self.placeholders(), [])
        self.assertEqual(self.ctrl.placeholder_nodes, {})

    def test_ir_module_type_6_gets_no_placeholder(self):
        self.discover_with({4: 6})
        self.assertEqual(self.placeholders(), [])
        self.assertEqual(len(self.ctrl.ir_nodes), 16)

    def test_empty_slot_marker_254_gets_no_placeholder(self):
        self.discover_with({1: 11})  # every other slot reports 254
        self.assertEqual(self.placeholders(), [])
        self.discover_with({1: 254})
        self.assertEqual(self.placeholders(), [])

    def test_mixed_modules_supported_ones_still_get_their_nodes(self):
        self.discover_with({1: 11, 2: 20, 3: 13, 4: 6, 5: 99})
        self.assertEqual(sorted(n.name for n in self.placeholders()), ['Mod 2 Type 20', 'Mod 5 Type 99'])
        self.assertEqual(len(self.ctrl.io_nodes), 16 + 8)  # SECU-16 and RLY08-XA
        self.assertEqual(len(self.ctrl.ir_nodes), 16)

    def test_placeholders_are_never_polled(self):
        self.discover_with({1: 11, 2: 20})
        addrs = {n.address for n in self.placeholders()}
        self.assertFalse(addrs & set(self.ctrl.io_nodes))
        self.assertFalse(any(isinstance(n, on.OcelotPlaceholder) for n in self.ctrl.io_nodes.values()))

    def test_repeated_discovery_does_not_duplicate_placeholders(self):
        self.discover_with({5: 20})
        self.discover_with({5: 20})
        self.discover_with({5: 20})
        self.assertEqual(len(self.placeholders()), 1)
        self.assertEqual(self.poly.deleted, [])

    def test_a_module_that_reports_another_type_replaces_its_placeholder(self):
        self.discover_with({5: 20})
        self.discover_with({5: 21})
        self.assertEqual([n.name for n in self.placeholders()], ['Mod 5 Type 20', 'Mod 5 Type 21'])
        self.assertEqual(self.poly.deleted, ['u5t20'])
        self.assertEqual(list(self.ctrl.placeholder_nodes), ['u5t21'])

    def test_a_module_that_disappears_loses_its_placeholder(self):
        self.discover_with({5: 20, 6: 30})
        self.discover_with({6: 30})
        self.assertEqual(self.poly.deleted, ['u5t20'])
        self.assertEqual(list(self.ctrl.placeholder_nodes), ['u6t30'])

    def test_a_module_that_becomes_supported_loses_its_placeholder(self):
        self.discover_with({5: 20})
        self.discover_with({5: 11})
        self.assertEqual(self.poly.deleted, ['u5t20'])
        self.assertEqual(self.ctrl.placeholder_nodes, {})
        self.assertEqual(len(self.ctrl.io_nodes), 16)

    def test_a_failed_delete_does_not_stop_discovery(self):
        self.discover_with({5: 20})

        def boom(address):
            raise RuntimeError('no such node')
        self.poly.delNode = boom
        self.discover_with({})  # must not raise
        self.assertEqual(self.ctrl.placeholder_nodes, {})
        self.assertTrue(self.ctrl.ocelot_ready)

    def test_the_old_unsupported_modules_notice_is_not_shown(self):
        self.discover_with({5: 20})
        self.assertNotIn('units', self.poly.Notices.items)

    def test_discovery_with_no_answer_changes_nothing(self):
        self.discover_with({5: 20})
        self.reply = None
        oc.discover(self.ctrl)
        self.assertEqual(len(self.placeholders()), 1)
        self.assertEqual(self.poly.deleted, [])

    def test_missing_placeholder_registry_is_created(self):
        del self.ctrl.placeholder_nodes
        self.discover_with({5: 20})
        self.assertEqual(list(self.ctrl.placeholder_nodes), ['u5t20'])

    def test_query_reports_the_placeholders_too(self):
        self.discover_with({5: 20})
        self.poly.sent.clear()
        oc.query(self.ctrl)
        reported = [m['set'][0]['address'] for m, kind in self.poly.sent if m.get('set')]
        self.assertIn('u5t20', reported)


class PlaceholderHelperTests(unittest.TestCase):
    def test_name_and_address(self):
        self.assertEqual(op.placeholder_name(5, 20), 'Mod 5 Type 20')
        self.assertEqual(op.placeholder_address(5, 20), 'u5t20')
        self.assertEqual(op.placeholder_name(128, 255), 'Mod 128 Type 255')

    def test_address_fits_the_node_address_limit(self):
        for unit in (1, 9, 10, 99, 128):
            for utype in (0, 7, 100, 255):
                addr = op.placeholder_address(unit, utype)
                self.assertLessEqual(len(addr), 14)
                self.assertRegex(addr, r'^[a-z0-9_]+$')

    def test_address_cannot_clash_with_other_node_addresses(self):
        mine = {op.placeholder_address(u, t) for u in range(1, 129) for t in range(0, 256)}
        others = set()
        for u in range(1, 129):
            others |= {'u%dr%d' % (u, i) for i in range(8)} | {'u%di%d' % (u, i) for i in range(16)}
            others |= {'u%dz%d' % (u, z) for z in range(16)} | {'u%dir' % u}
        others |= {'residentir', 'cpuxavars', 'ctl'}
        self.assertFalse(mine & others)
        self.assertEqual(len(mine), 128 * 256)

    def test_classify_units_unsupported_set(self):
        supported, unsupported, empty = op.classify_units({1: 11, 2: 12, 3: 13, 4: 6, 5: 20, 6: 254, 7: 1})
        self.assertEqual(sorted(supported), [1, 2, 3, 4])
        self.assertEqual(unsupported, {5: 20, 7: 1})
        self.assertEqual(empty, [6])


if __name__ == '__main__':
    unittest.main()
