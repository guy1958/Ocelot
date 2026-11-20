'''1.19.0: one property per program variable (VAR_0 .. VAR_127) on the Ocelot Variables node.

1.20.0: the properties are also editable; the command side is covered in test_ocelot_varedit.py.'''
import json
import os
import re
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

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profile.json')
PER_VARIABLE = re.compile('^VAR_[0-9]+$')
VALID_ID = re.compile('^[A-Z][A-Z0-9_]{0,29}$')
OLD_PROPERTIES = ['ST', 'VAR_NUM', 'VAR_VAL', 'READ_RESULT', 'READ_VAR', 'READ_VAL']
OLD_COMMANDS = {'SETVAR', 'GETVARS', 'READVAR'}


def load_profile():
    with open(PROFILE_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def cpuxavar():
    return [n for n in load_profile()['nodedefs'] if n['id'] == 'cpuxavar'][0]


def reply_data(values):
    '''The 256 data bytes of a Get Variables reply holding {variable: value} (LSB first), every other variable 0.'''
    data = bytearray(256)
    for n, v in values.items():
        data[2 * n] = v & 0xFF
        data[2 * n + 1] = v >> 8
    return bytes(data)


class ProfileTests(unittest.TestCase):
    def test_one_property_per_variable(self):
        ids = [p['id'] for p in cpuxavar()['properties']]
        for n in range(128):
            self.assertIn('VAR_%d' % n, ids)
        self.assertEqual(len([i for i in ids if PER_VARIABLE.match(i)]), 128)
        self.assertNotIn('VAR_128', ids)

    def test_property_ids_are_unique_and_valid(self):
        ids = [p['id'] for p in cpuxavar()['properties']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 6 + 128)
        for i in ids:
            self.assertRegex(i, VALID_ID)

    def test_every_variable_property_uses_the_value_editor(self):
        for p in cpuxavar()['properties']:
            if PER_VARIABLE.match(p['id']):
                self.assertEqual(p['editor'], 'ocelot_var_val', p['id'])

    def test_value_editor_is_an_unsigned_16_bit_number(self):
        editors = {e['id']: e for e in load_profile()['editors']}
        (rng,) = editors['ocelot_var_val']['ranges']
        self.assertEqual((rng['uom'], rng['min'], rng['max']), ('108', 0, 65535))

    def test_existing_properties_are_kept_first_and_unchanged(self):
        props = cpuxavar()['properties']
        self.assertEqual([p['id'] for p in props[:6]], OLD_PROPERTIES)
        self.assertEqual((props[0]['name'], props[0]['editor']), ('Last Write Result', 'ocelot_write_result'))
        self.assertEqual((props[5]['name'], props[5]['editor']), ('Read Value', 'ocelot_var_val'))

    def test_the_original_commands_are_still_there_and_every_command_is_dispatched(self):
        accepted = {c['id'] for c in cpuxavar()['cmds']['accepts']}
        self.assertTrue(OLD_COMMANDS <= accepted)
        self.assertEqual(len(accepted), 3 + 128)
        self.assertEqual(set(on.OcelotVariables.commands), accepted)

    def test_names(self):
        names = {p['id']: p['name'] for p in cpuxavar()['properties']}
        self.assertEqual(names['VAR_0'], 'Variable 0')
        self.assertEqual(names['VAR_17'], 'Variable 17')
        self.assertEqual(names['VAR_127'], 'Variable 127')
        for n in (60, 61, 62, 63):
            self.assertTrue(names['VAR_%d' % n].startswith('Variable %d ' % n), n)


class DriverTests(unittest.TestCase):
    def test_drivers_match_the_profile_properties(self):
        profile_ids = [p['id'] for p in cpuxavar()['properties']]
        driver_ids = [d['driver'] for d in on.OcelotVariables.drivers]
        self.assertEqual(sorted(profile_ids), sorted(driver_ids))
        self.assertEqual(len(driver_ids), len(set(driver_ids)))

    def test_variable_drivers_are_unsigned_16_bit_values_starting_at_zero(self):
        by_id = {d['driver']: d for d in on.OcelotVariables.drivers}
        for n in range(128):
            d = by_id['VAR_%d' % n]
            self.assertEqual((d['uom'], d['value']), (108, 0))

    def test_old_drivers_are_unchanged(self):
        by_id = {d['driver']: d for d in on.OcelotVariables.drivers}
        self.assertEqual(by_id['ST']['uom'], 25)
        self.assertEqual(by_id['READ_RESULT']['uom'], 25)
        self.assertEqual(by_id['VAR_NUM']['uom'], 107)
        self.assertEqual(by_id['READ_VAR']['uom'], 107)
        self.assertEqual(by_id['VAR_VAL']['uom'], 108)
        self.assertEqual(by_id['READ_VAL']['uom'], 108)

    def test_the_class_does_not_share_driver_dicts_with_the_module_list(self):
        by_id = {d['driver']: d for d in on.OcelotVariables.drivers}
        for d in on.VARIABLE_DRIVERS:
            self.assertIsNot(by_id[d['driver']], d)

    def test_every_variable_number_has_a_driver(self):
        self.assertEqual([d['driver'] for d in on.VARIABLE_DRIVERS], ['VAR_%d' % n for n in range(op.VARIABLE_COUNT)])


class FakePoly:
    '''Just enough of the Interface for udi_interface.Node.__init__ (no stored driver values).'''

    def db_getNodeDrivers(self, address):
        return []


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = (op.get_variables, op.write_variable)
        self.reply = reply_data({})
        op.get_variables = lambda ser: self.reply
        op.write_variable = lambda ser, vnum, value: True

    def tearDown(self):
        op.get_variables, op.write_variable = self._orig

    def node(self):
        n = on.OcelotVariables.__new__(on.OcelotVariables)
        n.address = 'cpuxavars'
        n.ctrl = types.SimpleNamespace(ser=object())
        n.values = None
        n.read_var = 0
        n.setDriver = lambda driver, value, *a, **k: self.calls.append((driver, value))
        return n

    def var_calls(self):
        return [(d, v) for d, v in self.calls if PER_VARIABLE.match(d)]

    def last(self, driver):
        return [v for d, v in self.calls if d == driver][-1]

    def test_a_new_node_has_published_nothing(self):
        n = on.OcelotVariables(FakePoly(), 'ctl', 'cpuxavars', 'Ocelot Variables', types.SimpleNamespace(ser=None))
        self.assertIsNone(n.published)

    def test_first_read_publishes_every_variable(self):
        self.reply = reply_data({58: 999, 59: 1001})
        n = self.node()
        self.assertTrue(n.refresh())
        calls = self.var_calls()
        self.assertEqual(len(calls), 128)
        self.assertEqual(len({d for d, v in calls}), 128)
        published = dict(calls)
        self.assertEqual(published['VAR_58'], 999)
        self.assertEqual(published['VAR_59'], 1001)
        self.assertEqual(published['VAR_0'], 0)
        self.assertEqual(published['VAR_127'], 0)

    def test_full_range_of_values(self):
        self.reply = reply_data({0: 65535, 1: 256, 127: 255})
        n = self.node()
        n.refresh()
        published = dict(self.var_calls())
        self.assertEqual((published['VAR_0'], published['VAR_1'], published['VAR_127']), (65535, 256, 255))

    def test_an_identical_second_read_sends_nothing(self):
        self.reply = reply_data({58: 999})
        n = self.node()
        n.refresh()
        self.calls.clear()
        n.refresh(quiet=True)
        self.assertEqual(self.var_calls(), [])

    def test_only_the_changed_variable_is_sent_again(self):
        self.reply = reply_data({58: 999, 59: 1001})
        n = self.node()
        n.refresh()
        self.calls.clear()
        self.reply = reply_data({58: 1000, 59: 1001})
        n.refresh()
        self.assertEqual(self.var_calls(), [('VAR_58', 1000)])

    def test_a_value_that_goes_back_is_sent_again(self):
        n = self.node()
        sent = []
        for value in (999, 5, 999):
            self.reply = reply_data({3: value})
            self.calls.clear()
            n.refresh()
            sent.extend(v for d, v in self.var_calls() if d == 'VAR_3')
        self.assertEqual(sent, [999, 5, 999])
        self.assertEqual(n.published[3], 999)

    def test_each_change_is_reported_once_in_order(self):
        n = self.node()
        sent = []
        for value in (7, 8, 8, 7):
            self.reply = reply_data({3: value})
            self.calls.clear()
            n.refresh()
            sent.extend(v for d, v in self.var_calls() if d == 'VAR_3')
        self.assertEqual(sent, [7, 8, 7])

    def test_a_failed_read_publishes_nothing_and_says_so(self):
        n = self.node()
        self.reply = None
        self.assertFalse(n.refresh())
        self.assertEqual(self.var_calls(), [])
        self.assertEqual(self.last('READ_RESULT'), 2)
        self.assertIsNone(n.values)

    def test_a_failed_read_keeps_what_was_published(self):
        self.reply = reply_data({58: 999})
        n = self.node()
        n.refresh()
        self.reply = None
        n.refresh()
        self.reply = reply_data({58: 999})
        self.calls.clear()
        n.refresh()
        self.assertEqual(self.var_calls(), [])
        self.assertEqual(n.values[58], 999)

    def test_a_closed_port_publishes_nothing(self):
        n = self.node()
        n.ctrl = types.SimpleNamespace(ser=None)
        self.assertFalse(n.refresh())
        self.assertEqual(self.var_calls(), [])

    def test_a_read_that_raises_publishes_nothing(self):
        def boom(ser):
            raise RuntimeError('link down')
        op.get_variables = boom
        n = self.node()
        self.assertFalse(n.refresh())
        self.assertEqual(self.var_calls(), [])

    def test_a_write_is_followed_by_a_read_that_publishes_the_written_variable(self):
        self.reply = reply_data({10: 1234})
        n = self.node()
        n.set_var({'cmd': 'SETVAR', 'query': {'VARNUM.uom107': '10', 'VALUE.uom108': '1234'}})
        self.assertEqual(dict(self.var_calls())['VAR_10'], 1234)
        # the last-write properties are still the plain, non-per-variable ones
        self.assertEqual(self.last('VAR_NUM'), 10)
        self.assertEqual(self.last('VAR_VAL'), 1234)
        self.assertEqual(self.last('ST'), 1)

    def test_the_selected_variable_is_still_shown_in_read_value(self):
        self.reply = reply_data({10: 1234})
        n = self.node()
        n.read_var = 10
        n.refresh()
        self.assertEqual(self.last('READ_VAR'), 10)
        self.assertEqual(self.last('READ_VAL'), 1234)

    def test_get_and_read_commands_publish_too(self):
        self.reply = reply_data({12: 77})
        n = self.node()
        n.get_vars()
        self.assertEqual(dict(self.var_calls())['VAR_12'], 77)
        self.reply = reply_data({12: 78})
        self.calls.clear()
        n.read_variable({'query': {'VARNUM.uom107': '12'}})
        self.assertEqual(self.var_calls(), [('VAR_12', 78)])

    def test_the_short_poll_refresh_publishes(self):
        self.reply = reply_data({40: 4000})
        n = self.node()
        ctrl = types.SimpleNamespace(var_node=n, ser=object())
        oc._refresh_variables(ctrl, quiet=True)
        self.assertEqual(dict(self.var_calls())['VAR_40'], 4000)

    def test_publishing_with_no_table_does_nothing(self):
        n = self.node()
        n.publish_values()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
