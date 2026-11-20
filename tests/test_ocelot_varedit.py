'''1.20.0: every VAR_<n> property of the Ocelot Variables node is editable (a VAR_<n> command with one unnamed value).

1.20.1: the edit commands carried no 'init' and 'optional' fields, to keep the profile small.
1.20.2: 'init' (equal to the property's own id) is back, as in the editable properties of other
families stored by IoX; 'optional' and 'native' stay out of the edit commands.'''
import json
import os
import re
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

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profile.json')
PER_VARIABLE = re.compile('^VAR_[0-9]+$')


def load_profile():
    with open(PROFILE_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def cpuxavar():
    return [n for n in load_profile()['nodedefs'] if n['id'] == 'cpuxavar'][0]


def reply_data(values):
    data = bytearray(256)
    for n, v in values.items():
        data[2 * n] = v & 0xFF
        data[2 * n + 1] = v >> 8
    return bytes(data)


class ProfileTests(unittest.TestCase):
    def commands(self):
        return {c['id']: c for c in cpuxavar()['cmds']['accepts']}

    def test_one_command_per_variable_with_the_property_id(self):
        cmds = self.commands()
        props = [p['id'] for p in cpuxavar()['properties'] if PER_VARIABLE.match(p['id'])]
        self.assertEqual(len(props), 128)
        for pid in props:
            self.assertIn(pid, cmds)
        self.assertEqual(len([c for c in cmds if PER_VARIABLE.match(c)]), 128)

    def test_the_last_write_properties_have_no_edit_command(self):
        cmds = self.commands()
        for pid in ('VAR_NUM', 'VAR_VAL', 'READ_VAR', 'READ_VAL', 'READ_RESULT', 'ST'):
            self.assertNotIn(pid, cmds)

    def test_each_edit_command_has_one_unnamed_value_parameter_initialised_from_its_property(self):
        for cid, cmd in self.commands().items():
            if not PER_VARIABLE.match(cid):
                continue
            (param,) = cmd['parameters']
            self.assertEqual(param['id'], '', cid)
            self.assertEqual(param['editor'], 'ocelot_var_val', cid)
            # the pattern of the editable properties in other stored families: init = the property's own id
            self.assertEqual(param['init'], cid, cid)
            # kept out of the edit commands to keep the profile small
            self.assertNotIn('optional', param, cid)
            self.assertNotIn('native', cmd, cid)

    def test_every_init_names_a_real_property(self):
        props = {p['id'] for p in cpuxavar()['properties']}
        for cid, cmd in self.commands().items():
            for param in cmd.get('parameters', []):
                if 'init' in param:
                    self.assertIn(param['init'], props, cid)

    def test_edit_command_names_match_the_property_names(self):
        names = {p['id']: p['name'] for p in cpuxavar()['properties']}
        for cid, cmd in self.commands().items():
            if PER_VARIABLE.match(cid):
                self.assertEqual(cmd['name'], names[cid], cid)

    def test_write_variable_keeps_its_two_named_parameters(self):
        cmd = self.commands()['SETVAR']
        self.assertEqual([p['id'] for p in cmd['parameters']], ['VARNUM', 'VALUE'])

    def test_the_profile_stays_small(self):
        size = len(json.dumps(load_profile(), separators=(',', ':')))
        self.assertLess(size, 30000, size)

    def test_every_accepted_command_has_a_distinct_dispatch_entry(self):
        accepted = set(self.commands())
        table = on.OcelotVariables.commands
        self.assertEqual(set(table), accepted)
        for cid in accepted:
            self.assertTrue(callable(table[cid]), cid)
        edit_functions = [table[c] for c in accepted if PER_VARIABLE.match(c)]
        self.assertEqual(len({id(f) for f in edit_functions}), 128)


class ParseSingleValueTests(unittest.TestCase):
    def test_value_field(self):
        self.assertEqual(on.parse_single_value({'cmd': 'VAR_3', 'value': '5', 'uom': '108'}), 5)
        self.assertEqual(on.parse_single_value({'value': 0}), 0)
        self.assertEqual(on.parse_single_value({'value': 65535}), 65535)
        self.assertEqual(on.parse_single_value({'value': '1234.0'}), 1234)

    def test_the_only_query_entry_is_used_when_there_is_no_value(self):
        self.assertEqual(on.parse_single_value({'query': {'.uom108': '7'}}), 7)
        self.assertEqual(on.parse_single_value({'query': {'': 9}}), 9)
        self.assertEqual(on.parse_single_value({'value': None, 'query': {'.uom108': '11'}}), 11)

    def test_the_value_field_wins_over_query(self):
        self.assertEqual(on.parse_single_value({'value': '4', 'query': {'.uom108': '99'}}), 4)

    def test_bad_input_is_rejected(self):
        for cmd in (None, {}, {'value': None}, {'value': 'x'}, {'value': ''}, {'value': -1}, {'value': 65536},
                    {'value': 'inf'}, {'value': 'nan'}, {'query': {}}, {'query': {'a': 1, 'b': 2}}):
            with self.assertRaises(ValueError, msg=str(cmd)):
                on.parse_single_value(cmd)


class EditTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.written = []
        self.reads = 0
        self._orig = (op.get_variables, op.write_variable)
        self.reply = reply_data({})
        self.write_result = True
        self.write_raises = False

        def fake_get(ser):
            self.reads += 1
            return self.reply

        def fake_write(ser, vnum, value):
            self.written.append((vnum, value))
            if self.write_raises:
                raise RuntimeError('link down')
            return self.write_result

        op.get_variables = fake_get
        op.write_variable = fake_write

    def tearDown(self):
        op.get_variables, op.write_variable = self._orig

    def node(self, ser=True):
        n = on.OcelotVariables.__new__(on.OcelotVariables)
        n.address = 'cpuxavars'
        n.ctrl = types.SimpleNamespace(ser=object() if ser else None)
        n.values = None
        n.read_var = 0
        n.setDriver = lambda driver, value, *a, **k: self.calls.append((driver, value))
        return n

    def last(self, driver):
        return [v for d, v in self.calls if d == driver][-1]

    def edit(self, n, vnum, value):
        on.OcelotVariables.commands['VAR_%d' % vnum](n, {'cmd': 'VAR_%d' % vnum, 'value': str(value), 'uom': '108'})

    def test_editing_a_property_writes_that_variable_and_publishes_it(self):
        self.reply = reply_data({17: 1234})
        n = self.node()
        self.edit(n, 17, 1234)
        self.assertEqual(self.written, [(17, 1234)])
        self.assertEqual(self.last('ST'), 1)
        self.assertEqual(self.last('VAR_NUM'), 17)
        self.assertEqual(self.last('VAR_VAL'), 1234)
        self.assertEqual(self.last('VAR_17'), 1234)
        self.assertEqual(self.reads, 1)

    def test_every_variable_command_writes_its_own_variable(self):
        for vnum in range(128):
            self.written.clear()
            n = self.node()
            self.edit(n, vnum, 5)
            self.assertEqual(self.written, [(vnum, 5)], vnum)

    def test_edge_values(self):
        n = self.node()
        self.edit(n, 0, 0)
        self.edit(n, 127, 65535)
        self.assertEqual(self.written, [(0, 0), (127, 65535)])

    def test_a_bad_value_writes_nothing_and_does_not_read(self):
        for bad in ('x', '-1', '65536', ''):
            self.written.clear()
            self.reads = 0
            n = self.node()
            self.edit(n, 5, bad)
            self.assertEqual(self.written, [], bad)
            self.assertEqual(self.reads, 0, bad)
            self.assertEqual(self.last('ST'), 2, bad)

    def test_a_missing_value_writes_nothing(self):
        n = self.node()
        on.OcelotVariables.commands['VAR_5'](n, {'cmd': 'VAR_5'})
        on.OcelotVariables.commands['VAR_5'](n, None)
        self.assertEqual(self.written, [])
        self.assertEqual(self.last('ST'), 2)

    def test_a_closed_port_writes_nothing(self):
        n = self.node(ser=False)
        self.edit(n, 5, 7)
        self.assertEqual(self.written, [])
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.last('ST'), 2)

    def test_a_write_that_raises_is_reported_and_not_followed_by_a_read(self):
        self.write_raises = True
        n = self.node()
        self.edit(n, 5, 7)
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.last('ST'), 2)

    def test_an_unacknowledged_write_is_reported_and_the_property_shows_what_the_ocelot_holds(self):
        self.write_result = False
        self.reply = reply_data({5: 3})
        n = self.node()
        self.edit(n, 5, 7)
        self.assertEqual(self.last('ST'), 2)
        self.assertEqual(self.reads, 1)
        self.assertEqual(self.last('VAR_5'), 3)
        self.assertNotIn(('VAR_VAL', 7), self.calls)

    def test_an_unreadable_follow_up_keeps_the_write_result(self):
        self.reply = None
        n = self.node()
        self.edit(n, 5, 7)
        self.assertEqual(self.last('ST'), 1)
        self.assertEqual(self.last('READ_RESULT'), 2)
        self.assertNotIn('VAR_5', [d for d, v in self.calls])

    def test_write_variable_command_still_works(self):
        self.reply = reply_data({10: 1234})
        n = self.node()
        on.OcelotVariables.commands['SETVAR'](n, {'cmd': 'SETVAR', 'query': {'VARNUM.uom107': '10', 'VALUE.uom108': '1234'}})
        self.assertEqual(self.written, [(10, 1234)])
        self.assertEqual(self.last('VAR_10'), 1234)

    def test_write_variable_with_bad_parameters_still_writes_nothing(self):
        n = self.node()
        on.OcelotVariables.commands['SETVAR'](n, {'query': {'VARNUM': 128, 'VALUE': 1}})
        self.assertEqual(self.written, [])
        self.assertEqual(self.last('ST'), 2)


if __name__ == '__main__':
    unittest.main()
