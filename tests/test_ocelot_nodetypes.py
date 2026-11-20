'''1.17.0: every kind of module point has its own node type (profile nodedef).'''
import inspect
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import test_ocelot_delete as base  # also sets up the udi_interface stand-in when the real package is absent
import ocelot_nodes as on
import ocelot_proto as op

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profile.json')


def load_profile():
    with open(PROFILE_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def node_type_ids():
    '''The node type ids the node classes declare themselves (a class that only inherits one does not count).'''
    ids = {}
    for name, cls in inspect.getmembers(on, inspect.isclass):
        if cls.__module__ == on.__name__ and 'id' in vars(cls):
            ids[name] = vars(cls)['id']
    return ids


class NodeTypeByModuleTests(base.DeleteTestBase):
    def addr_ids(self):
        return {n.address: n.id for n in self.poly.added}

    def test_secu16_gets_secu16_input_and_relay_types(self):
        self.discover_with({1: 11})
        ids = self.addr_ids()
        for i in range(8):
            self.assertEqual(ids['u1i%d' % i], 'secu16_input')
            self.assertEqual(ids['u1r%d' % i], 'secu16_relay')

    def test_secu16i_gets_secu16i_input_type_and_no_relays(self):
        self.discover_with({2: 12})
        ids = self.addr_ids()
        for i in range(16):
            self.assertEqual(ids['u2i%d' % i], 'secu16i_input')
        self.assertFalse([a for a in ids if a.startswith('u2r')])

    def test_rly08xa_gets_rly08xa_relay_type(self):
        self.discover_with({3: 13})
        ids = self.addr_ids()
        for i in range(8):
            self.assertEqual(ids['u3r%d' % i], 'rly08xa_relay')
        self.assertFalse([a for a in ids if a.startswith('u3i')])

    def test_secu16ir_zones_get_secu16ir_zone_type(self):
        self.discover_with({4: 6})
        ids = self.addr_ids()
        for z in range(16):
            self.assertEqual(ids['u4z%d' % z], 'secu16ir_zone')

    def test_unsupported_module_keeps_the_placeholder_type(self):
        self.discover_with({5: 20})
        self.assertEqual(self.addr_ids()['u5t20'], 'placeholder')

    def test_every_module_kind_at_once_uses_only_the_new_types(self):
        self.discover_with({1: 11, 2: 12, 3: 13, 4: 6, 5: 20})
        used = {n.id for n in self.poly.added if n.address not in ('residentir', 'cpuxavars')}
        self.assertEqual(used, {'secu16_input', 'secu16_relay', 'secu16i_input', 'rly08xa_relay',
                                'secu16ir_zone', 'placeholder'})
        for old in ('relay', 'input', 'irzone'):
            self.assertNotIn(old, used)

    def test_node_classes_keep_the_relay_and_input_behaviour(self):
        self.discover_with({1: 11, 2: 12, 3: 13})
        for node in self.ctrl.io_nodes.values():
            if node.address[2] == 'r':
                self.assertIsInstance(node, on.OcelotRelay)
            else:
                self.assertIsInstance(node, on.OcelotInput)
        # source assignment is unchanged: SECU-16 / SECU-16I latched, RLY08-XA real time
        self.assertEqual(self.ctrl.io_nodes['u1r0'].source, op.SOURCE_LATCHED)
        self.assertEqual(self.ctrl.io_nodes['u2i0'].source, op.SOURCE_LATCHED)
        self.assertEqual(self.ctrl.io_nodes['u3r0'].source, op.SOURCE_REALTIME)

    def test_names_and_addresses_are_unchanged(self):
        self.discover_with({2: 12})
        node = [n for n in self.poly.added if n.address == 'u2i0'][0]
        self.assertEqual(node.name, 'Mod 2 Input 0')

    def test_io_node_class_covers_every_point_kind_the_protocol_returns(self):
        for utype in (op.TYPE_SECU16, op.TYPE_SECU16I, op.TYPE_RLY08XA):
            for kind, idx, byte, bit in op.points_for_unit(utype):
                self.assertTrue(issubclass(on.io_node_class(utype, kind), on.OcelotRelay if kind == 'relay' else on.OcelotInput))

    def test_io_node_class_rejects_a_combination_that_does_not_exist(self):
        with self.assertRaises(KeyError):
            on.io_node_class(op.TYPE_SECU16I, 'relay')
        with self.assertRaises(KeyError):
            on.io_node_class(op.TYPE_RLY08XA, 'input')


class RelayCommandTests(unittest.TestCase):
    '''The RLY08-XA relay has its own class and command table; it must still switch the relay like the SECU-16 one.'''

    def setUp(self):
        self._orig = op.write_relay
        self.written = []
        op.write_relay = lambda ser, unit, relay, on: self.written.append((unit, relay, on)) or True
        self.set_calls = []

    def tearDown(self):
        op.write_relay = self._orig

    def make(self, cls):
        ctrl = type('Ctrl', (), {'ser': object(), 'ocelot_ready': False, 'io_nodes': {}})()
        node = cls(base.FakePoly(), 'ctl', 'u3r2', 'Mod 3 Relay 2', ctrl, 3, 2, 0, 2, op.SOURCE_REALTIME)
        node.setDriver = lambda *a, **k: self.set_calls.append((a, k))
        return node

    def test_rly08xa_command_table_switches_the_relay(self):
        node = self.make(on.Rly08xaRelay)
        self.assertEqual(set(on.Rly08xaRelay.commands), {'DON', 'DOF'})
        on.Rly08xaRelay.commands['DON'](node, {})
        on.Rly08xaRelay.commands['DOF'](node, {})
        self.assertEqual(self.written, [(3, 2, True), (3, 2, False)])
        self.assertEqual([c[0] for c in self.set_calls], [('ST', 1), ('ST', 0)])

    def test_secu16_command_table_still_switches_the_relay(self):
        node = self.make(on.Secu16Relay)
        on.Secu16Relay.commands['DON'](node, {})
        self.assertEqual(self.written, [(3, 2, True)])


class ProfileMatchesClassesTests(unittest.TestCase):
    def test_every_node_type_id_in_the_code_is_a_nodedef_and_the_reverse(self):
        profile_ids = {n['id'] for n in load_profile()['nodedefs']}
        code_ids = set(node_type_ids().values())
        # the controller's own nodedef is declared by the generated plugin.py, not by ocelot_nodes
        self.assertEqual(profile_ids - {'controller'}, code_ids)

    def test_the_secu16_classes_are_the_original_relay_and_input_classes(self):
        # OcelotRelay / OcelotInput keep their names (other code and tests build them directly); they are the SECU-16 types
        self.assertIs(on.Secu16Relay, on.OcelotRelay)
        self.assertIs(on.Secu16Input, on.OcelotInput)
        self.assertEqual(on.OcelotRelay.id, 'secu16_relay')
        self.assertEqual(on.OcelotInput.id, 'secu16_input')
        self.assertTrue(issubclass(on.Rly08xaRelay, on.OcelotRelay))
        self.assertTrue(issubclass(on.Secu16IInput, on.OcelotInput))

    def test_old_generic_types_are_gone_from_the_profile(self):
        profile_ids = {n['id'] for n in load_profile()['nodedefs']}
        for old in ('relay', 'input', 'irzone'):
            self.assertNotIn(old, profile_ids)

    def test_type_column_names(self):
        names = {n['id']: n['name'] for n in load_profile()['nodedefs']}
        self.assertEqual(names['secu16_input'], 'SECU16 Input')
        self.assertEqual(names['secu16_relay'], 'SECU16 Relay')
        self.assertEqual(names['secu16i_input'], 'SECU16I Input')
        self.assertEqual(names['rly08xa_relay'], 'RLY08XA Relay')
        self.assertEqual(names['secu16ir_zone'], 'SECU16IR Zone')

    def test_relay_types_are_identical_apart_from_id_and_name(self):
        nodedefs = {n['id']: n for n in load_profile()['nodedefs']}
        a, b = nodedefs['secu16_relay'], nodedefs['rly08xa_relay']
        self.assertEqual(a['properties'], b['properties'])
        self.assertEqual(a['cmds'], b['cmds'])
        self.assertEqual({c['id'] for c in a['cmds']['accepts']}, {'DON', 'DOF'})

    def test_input_types_are_identical_apart_from_id_and_name(self):
        nodedefs = {n['id']: n for n in load_profile()['nodedefs']}
        a, b = nodedefs['secu16_input'], nodedefs['secu16i_input']
        self.assertEqual(a['properties'], b['properties'])
        self.assertEqual(a['cmds'], b['cmds'])
        self.assertEqual({c['id'] for c in a['cmds']['sends']}, {'DON', 'DOF'})

    def test_every_non_controller_nodedef_has_an_st_property(self):
        for n in load_profile()['nodedefs']:
            self.assertIn('ST', [p['id'] for p in n['properties']], n['id'])

    def test_accepted_commands_have_a_dispatch_entry_in_the_class(self):
        nodedefs = {n['id']: n for n in load_profile()['nodedefs']}
        for name, cls in inspect.getmembers(on, inspect.isclass):
            if cls.__module__ != on.__name__:
                continue
            node_id = getattr(cls, 'id', None)
            if node_id in nodedefs and node_id != 'controller':
                accepted = {c['id'] for c in nodedefs[node_id]['cmds']['accepts']}
                self.assertEqual(accepted, set(getattr(cls, 'commands', {})), name)


if __name__ == '__main__':
    unittest.main()
