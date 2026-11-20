'''Node classes for the Ocelot plugin: expansion-module relays/inputs, IR outputs, program variables and placeholders.

Since 1.17.0 every kind of module point has its own node type (profile nodedef), so the admin console's
Type column names the module kind: SECU16 Input / SECU16 Relay (type 11), SECU16I Input (type 12),
RLY08XA Relay (type 13), SECU16IR Zone (type 6). OcelotRelay and OcelotInput are the SECU-16 classes
(also named Secu16Relay and Secu16Input) and the bases of the other two; use io_node_class() to get the
class for a module type.
'''
import udi_interface
import ocelot_proto as op

Node = udi_interface.Node
LOGGER = udi_interface.LOGGER

# 1.19.0: one property per program variable on the Ocelot Variables node, VAR_0 .. VAR_127
# (unsigned 16-bit, uom 108), so a Program can test any variable directly.
# 1.20.0: each of them is also editable: the node accepts a command with the same id (VAR_<n>) and
# one unnamed value parameter, which writes that variable (see OcelotVariables.edit_variable).
VAR_DRIVER_FORMAT = 'VAR_%d'
VARIABLE_DRIVERS = [{'driver': VAR_DRIVER_FORMAT % n, 'value': 0, 'uom': 108} for n in range(op.VARIABLE_COUNT)]


def parse_single_value(command):
    '''The value (0-65535) of a property-edit command, which has one unnamed parameter.

    PG3 delivers it as command['value']; if that is absent the only entry of command['query'] is
    used (its key is empty or just a unit, so it cannot be matched by name). Raises ValueError if the
    value is missing, ambiguous, not a number, or outside 0-65535.
    '''
    command = command or {}
    raw = command.get('value')
    if raw is None:
        query = command.get('query') or {}
        if len(query) == 1:
            raw = list(query.values())[0]
    if raw is None:
        raise ValueError('missing value')
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('value is not a number: %r' % (raw,))
    if not 0 <= value <= op.VARIABLE_VALUE_MAX:
        raise ValueError('value must be 0-%d, got %d' % (op.VARIABLE_VALUE_MAX, value))
    return value


def _variable_setter(vnum):
    '''The command function for editing variable vnum (used as a class-level entry of OcelotVariables.commands).'''
    def setter(self, command=None):
        self.edit_variable(vnum, command)
    setter.__name__ = 'set_variable_%d' % vnum
    return setter


class OcelotRelay(Node):
    '''One relay of a SECU-16 expansion module (node type 'SECU16 Relay'); the base of Rly08xaRelay.

    After an On/Off command the Ocelot acknowledged, the commanded state is sent to IoX at once
    (forced, so it is reported even if the plugin's cached value is the same). The latched I/O is
    then read (ocelot_ctl.poll with only the latched source), which refreshes the other relay and
    input nodes of the SECU-16 and SECU-16I modules; that read leaves this relay alone, because a
    latched relay bit right after a command can still carry the old state. No real-time read is made.

    source says which read supplies this node's data: op.SOURCE_LATCHED (SECU-16, SECU-16I) or
    op.SOURCE_REALTIME (RLY08-XA, the default).'''
    id = 'secu16_relay'
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 25}]

    def __init__(self, polyglot, primary, address, name, ctrl, unit, relay, byte, bit, source=op.SOURCE_REALTIME):
        super().__init__(polyglot, primary, address, name)
        self.ctrl = ctrl
        self.unit = unit
        self.relay = relay
        self.byte = byte
        self.bit = bit
        self.source = source

    def update_from(self, data):
        self.setDriver('ST', op.get_bit(data, self.unit, self.byte, self.bit))

    def _read_io(self, keep_state=False):
        '''Read the latched I/O now so the SECU-16 / SECU-16I inputs and relays show the state after the command.

        Only the latched read is made (installer's choice): RLY08-XA nodes are not refreshed here and
        keep the commanded state until the next regular poll. With no SECU-16 / SECU-16I nodes nothing
        is read. keep_state=True leaves this relay's own status as the command set it. Imported here
        because ocelot_ctl imports this module. A problem here never changes the command's own result.
        '''
        try:
            import ocelot_ctl
            ocelot_ctl.poll(self.ctrl, sources=(op.SOURCE_LATCHED,), skip=(self,) if keep_state else None)
        except Exception as ex:
            LOGGER.error('Relay %s: reading the inputs after the write failed: %s' % (self.address, ex))

    def _set(self, on):
        ser = getattr(self.ctrl, 'ser', None)
        if ser is None:
            LOGGER.error('Relay %s: serial port is not open' % self.address)
            return
        try:
            ok = op.write_relay(ser, self.unit, self.relay, on)
        except Exception as ex:
            LOGGER.error('Relay %s: write failed: %s' % (self.address, ex))
            return
        if ok:
            # Report it to IoX straight away, even if the cached value is already the same.
            self.setDriver('ST', 1 if on else 0, force=True)
        else:
            LOGGER.error('Relay %s: Ocelot did not acknowledge the command' % self.address)
        # The command reached the Ocelot (acknowledged or not; an unacknowledged one may still have
        # taken effect), so read the latched inputs and relays straight away. When the command was
        # acknowledged this relay keeps the state just set: that read can still show the old state.
        self._read_io(keep_state=ok)

    def don(self, command=None):
        self._set(True)

    def dof(self, command=None):
        self._set(False)

    commands = {'DON': don, 'DOF': dof}


Secu16Relay = OcelotRelay


class Rly08xaRelay(OcelotRelay):
    '''A relay of an RLY08-XA module (unit type 13); node type 'RLY08XA Relay'. Behaves exactly like OcelotRelay.

    It repeats the command table because the node type needs its own class-level commands.'''
    id = 'rly08xa_relay'

    def don(self, command=None):
        self._set(True)

    def dof(self, command=None):
        self._set(False)

    commands = {'DON': don, 'DOF': dof}


class OcelotInput(Node):
    '''One input bit of a SECU-16 expansion module (node type 'SECU16 Input'); the base of Secu16IInput.

    source says which read supplies it (see OcelotRelay).'''
    id = 'secu16_input'
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 25}]

    def __init__(self, polyglot, primary, address, name, unit, index, byte, bit, invert=False, source=op.SOURCE_REALTIME):
        super().__init__(polyglot, primary, address, name)
        self.unit = unit
        self.index = index
        self.byte = byte
        self.bit = bit
        self.invert = invert
        self.source = source

    def update_from(self, data):
        raw = op.get_bit(data, self.unit, self.byte, self.bit)
        val = (1 - raw) if self.invert else raw
        try:
            old = int(float(self.getDriver('ST')))
        except Exception:
            old = None
        self.setDriver('ST', val)
        if old is not None and old != val:
            self.reportCmd('DON' if val else 'DOF')


Secu16Input = OcelotInput


class Secu16IInput(OcelotInput):
    '''An input of a SECU-16I module (unit type 12); node type 'SECU16I Input'. Behaves exactly like OcelotInput.'''
    id = 'secu16i_input'


# (unit type code, 'relay' | 'input') -> node class. Every point kind points_for_unit() returns is here.
IO_NODE_CLASSES = {
    (op.TYPE_SECU16, 'input'): Secu16Input,
    (op.TYPE_SECU16, 'relay'): Secu16Relay,
    (op.TYPE_SECU16I, 'input'): Secu16IInput,
    (op.TYPE_RLY08XA, 'relay'): Rly08xaRelay,
}


def io_node_class(unit_type, kind):
    '''The node class for one point of a module: kind is 'relay' or 'input'. Raises KeyError for a combination that does not exist.'''
    return IO_NODE_CLASSES[(unit_type, kind)]


class OcelotPlaceholder(Node):
    '''Placeholder for an expansion module whose Get Unit Type code this plugin does not support.

    It has no commands and is never polled; its only property (ST, Module Type) is the type code the
    Ocelot reported. Named 'Mod <unit> Type <type>' by ocelot_ctl.discover().
    '''
    id = 'placeholder'
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 107}]
    commands = {}

    def __init__(self, polyglot, primary, address, name, unit, unit_type):
        super().__init__(polyglot, primary, address, name)
        self.unit = unit
        self.unit_type = unit_type
        # a fresh list (not an edit in place) so no other instance shares it; the value is shown when the node is added
        self.drivers = [dict(d, value=unit_type) if d['driver'] == 'ST' else dict(d) for d in self.drivers]


class OcelotIRZone(Node):
    '''One output zone of a SECU-16IR module (unit type 6); send-only. Node type 'SECU16IR Zone'.'''
    id = 'secu16ir_zone'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 25},
        {'driver': 'IR_NUM', 'value': 0, 'uom': 108},
    ]

    def __init__(self, polyglot, primary, address, name, ctrl, unit, zone):
        super().__init__(polyglot, primary, address, name)
        self.ctrl = ctrl
        self.unit = unit
        self.zone = zone

    def send_ir(self, command=None):
        try:
            irnum = op.parse_ir_number(command)
        except ValueError as ex:
            LOGGER.error('IR %s: bad Send IR parameter: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        ser = getattr(self.ctrl, 'ser', None)
        if ser is None:
            LOGGER.error('IR %s: serial port is not open' % self.address)
            self.setDriver('ST', 2)
            return
        try:
            ok = op.send_remote_ir(ser, self.unit, self.zone, irnum)
        except Exception as ex:
            LOGGER.error('IR %s: send failed: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        if ok:
            self.setDriver('IR_NUM', irnum)
            self.setDriver('ST', 1)
            LOGGER.info('IR %s: sent IR %d to module %d zone %d, acknowledged' % (self.address, irnum, self.unit, self.zone))
        else:
            LOGGER.error('IR %s: Ocelot did not acknowledge IR %d (module %d zone %d)' % (self.address, irnum, self.unit, self.zone))
            self.setDriver('ST', 2)

    commands = {'SENDIR': send_ir}


class OcelotResidentIR(Node):
    '''The Ocelot's own IR output (Send Resident IR); send-only.'''
    id = 'irresident'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 25},
        {'driver': 'IR_NUM', 'value': 0, 'uom': 108},
    ]

    def __init__(self, polyglot, primary, address, name, ctrl):
        super().__init__(polyglot, primary, address, name)
        self.ctrl = ctrl

    def send_ir(self, command=None):
        try:
            irnum = op.parse_ir_number(command, op.RESIDENT_IR_MAX)
        except ValueError as ex:
            LOGGER.error('Resident IR %s: bad Send Resident IR parameter: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        ser = getattr(self.ctrl, 'ser', None)
        if ser is None:
            LOGGER.error('Resident IR %s: serial port is not open' % self.address)
            self.setDriver('ST', 2)
            return
        try:
            ok = op.send_resident_ir(ser, irnum)
        except Exception as ex:
            LOGGER.error('Resident IR %s: send failed: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        if ok:
            self.setDriver('IR_NUM', irnum)
            self.setDriver('ST', 1)
            LOGGER.info('Resident IR %s: sent IR %d, acknowledged' % (self.address, irnum))
        else:
            LOGGER.error('Resident IR %s: Ocelot did not acknowledge IR %d' % (self.address, irnum))
            self.setDriver('ST', 2)

    commands = {'SENDIR': send_ir}


class OcelotVariables(Node):
    '''Program variables: Write Variable (command 41), plus Get Variables / Read Variable.

    Reading uses the installer-supplied Get Variables frame, which returns all 128 variables at once.
    The table is read on every short poll (right after the I/O read), immediately after a
    Write Variable that reached the Ocelot, and on request (Get Variables, Read Variable, Query, Discover).

    Since 1.19.0 every successful read is also published to one property per variable,
    VAR_0 .. VAR_127, so a Program can test any variable. Only a variable whose value differs from what
    was last published is sent (the first read after a start sends all 128).

    Since 1.20.0 each of those properties is also editable: the node accepts a command VAR_<n> (same id
    as the property) with one unnamed value parameter. It does the same write as Write Variable.
    '''
    id = 'cpuxavar'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 25},
        {'driver': 'VAR_NUM', 'value': 0, 'uom': 107},
        {'driver': 'VAR_VAL', 'value': 0, 'uom': 108},
        {'driver': 'READ_RESULT', 'value': 0, 'uom': 25},
        {'driver': 'READ_VAR', 'value': 0, 'uom': 107},
        {'driver': 'READ_VAL', 'value': 0, 'uom': 108},
    ] + [dict(d) for d in VARIABLE_DRIVERS]

    def __init__(self, polyglot, primary, address, name, ctrl):
        super().__init__(polyglot, primary, address, name)
        self.ctrl = ctrl
        self.values = None      # last successfully read table: list of 128 ints, or None
        self.read_var = 0       # the variable shown in Read Variable / Read Value
        self.published = None   # what VAR_0 .. VAR_127 were last sent as: list of 128 ints/None, or None

    def set_var(self, command=None):
        '''Write Variable: the variable number and the value are two named parameters.'''
        try:
            vnum, value = op.parse_variable_command(command)
        except ValueError as ex:
            LOGGER.error('Variables %s: bad Write Variable parameters: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        self.write_one(vnum, value)

    def edit_variable(self, vnum, command=None):
        '''Edit the property VAR_<vnum>: the command has one unnamed parameter, the new value.'''
        try:
            value = parse_single_value(command)
        except ValueError as ex:
            LOGGER.error('Variables %s: bad value for variable %d: %s' % (self.address, vnum, ex))
            self.setDriver('ST', 2)
            return
        self.write_one(vnum, value)

    def write_one(self, vnum, value):
        '''Write value (already checked) to variable vnum, report the result, then read all variables.'''
        ser = getattr(self.ctrl, 'ser', None)
        if ser is None:
            LOGGER.error('Variables %s: serial port is not open' % self.address)
            self.setDriver('ST', 2)
            return
        try:
            ok = op.write_variable(ser, vnum, value)
        except Exception as ex:
            LOGGER.error('Variables %s: write failed: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
        if ok:
            self.setDriver('VAR_NUM', vnum)
            self.setDriver('VAR_VAL', value)
            self.setDriver('ST', 1)
            LOGGER.info('Variables %s: wrote %d to variable %d, acknowledged' % (self.address, value, vnum))
        else:
            LOGGER.error('Variables %s: Ocelot did not acknowledge writing %d to variable %d' % (self.address, value, vnum))
            self.setDriver('ST', 2)
        # The write reached the Ocelot (acknowledged or not; an unacknowledged write may still have
        # taken effect), so read all variables straight away: Read Variable / Read Value then show
        # what the Ocelot actually holds. A failed read here never changes Last Write Result.
        self.refresh()

    def refresh(self, quiet=False):
        '''Read all 128 variables from the Ocelot. Returns True on success.

        On success the cache is replaced, every changed variable is published to its own VAR_<n>
        property, and Read Variable / Read Value show the selected variable.
        On failure the cache, the properties and the shown value are left as they were and Last Read Result says so.
        quiet=True (used by the short poll) logs the success line at debug level instead of info,
        so a read every few seconds does not flood the log. Failures are always logged as errors.
        '''
        ser = getattr(self.ctrl, 'ser', None)
        if ser is None:
            LOGGER.error('Variables %s: serial port is not open, cannot read variables' % self.address)
            self.setDriver('READ_RESULT', 2)
            return False
        try:
            data = op.get_variables(ser)
        except Exception as ex:
            LOGGER.error('Variables %s: read failed: %s' % (self.address, ex))
            data = None
        if data is None:
            LOGGER.error('Variables %s: no valid answer to Get Variables' % self.address)
            self.setDriver('READ_RESULT', 2)
            return False
        self.values = op.parse_variables(data)
        self.setDriver('READ_RESULT', 1)
        self.publish_values()
        self.show_selected()
        log = LOGGER.debug if quiet else LOGGER.info
        log('Variables %s: read %d variables, %d non-zero' % (self.address, len(self.values), sum(1 for v in self.values if v)))
        return True

    def publish_values(self):
        '''Send each variable that changed since the last publish to its own VAR_<n> property.

        The first call after a start sends all of them. Unchanged variables are not sent again, so a
        poll every few seconds does not make 128 setDriver calls (and 128 debug lines) each time.
        '''
        if self.values is None:
            return
        last = getattr(self, 'published', None)
        if last is None or len(last) != len(self.values):
            last = self.published = [None] * len(self.values)
        for n, value in enumerate(self.values):
            if last[n] != value:
                self.setDriver(VAR_DRIVER_FORMAT % n, value)
                last[n] = value

    def show_selected(self):
        if self.values is None:
            return
        self.setDriver('READ_VAR', self.read_var)
        self.setDriver('READ_VAL', self.values[self.read_var])

    def get_vars(self, command=None):
        self.refresh()

    def read_variable(self, command=None):
        try:
            vnum = op.parse_variable_number(command)
        except ValueError as ex:
            LOGGER.error('Variables %s: bad Read Variable parameter: %s' % (self.address, ex))
            self.setDriver('READ_RESULT', 2)
            return
        self.read_var = vnum
        self.refresh()

    # One command function per variable: editing the property VAR_<n> runs var_<n>.
    var_0 = _variable_setter(0)
    var_1 = _variable_setter(1)
    var_2 = _variable_setter(2)
    var_3 = _variable_setter(3)
    var_4 = _variable_setter(4)
    var_5 = _variable_setter(5)
    var_6 = _variable_setter(6)
    var_7 = _variable_setter(7)
    var_8 = _variable_setter(8)
    var_9 = _variable_setter(9)
    var_10 = _variable_setter(10)
    var_11 = _variable_setter(11)
    var_12 = _variable_setter(12)
    var_13 = _variable_setter(13)
    var_14 = _variable_setter(14)
    var_15 = _variable_setter(15)
    var_16 = _variable_setter(16)
    var_17 = _variable_setter(17)
    var_18 = _variable_setter(18)
    var_19 = _variable_setter(19)
    var_20 = _variable_setter(20)
    var_21 = _variable_setter(21)
    var_22 = _variable_setter(22)
    var_23 = _variable_setter(23)
    var_24 = _variable_setter(24)
    var_25 = _variable_setter(25)
    var_26 = _variable_setter(26)
    var_27 = _variable_setter(27)
    var_28 = _variable_setter(28)
    var_29 = _variable_setter(29)
    var_30 = _variable_setter(30)
    var_31 = _variable_setter(31)
    var_32 = _variable_setter(32)
    var_33 = _variable_setter(33)
    var_34 = _variable_setter(34)
    var_35 = _variable_setter(35)
    var_36 = _variable_setter(36)
    var_37 = _variable_setter(37)
    var_38 = _variable_setter(38)
    var_39 = _variable_setter(39)
    var_40 = _variable_setter(40)
    var_41 = _variable_setter(41)
    var_42 = _variable_setter(42)
    var_43 = _variable_setter(43)
    var_44 = _variable_setter(44)
    var_45 = _variable_setter(45)
    var_46 = _variable_setter(46)
    var_47 = _variable_setter(47)
    var_48 = _variable_setter(48)
    var_49 = _variable_setter(49)
    var_50 = _variable_setter(50)
    var_51 = _variable_setter(51)
    var_52 = _variable_setter(52)
    var_53 = _variable_setter(53)
    var_54 = _variable_setter(54)
    var_55 = _variable_setter(55)
    var_56 = _variable_setter(56)
    var_57 = _variable_setter(57)
    var_58 = _variable_setter(58)
    var_59 = _variable_setter(59)
    var_60 = _variable_setter(60)
    var_61 = _variable_setter(61)
    var_62 = _variable_setter(62)
    var_63 = _variable_setter(63)
    var_64 = _variable_setter(64)
    var_65 = _variable_setter(65)
    var_66 = _variable_setter(66)
    var_67 = _variable_setter(67)
    var_68 = _variable_setter(68)
    var_69 = _variable_setter(69)
    var_70 = _variable_setter(70)
    var_71 = _variable_setter(71)
    var_72 = _variable_setter(72)
    var_73 = _variable_setter(73)
    var_74 = _variable_setter(74)
    var_75 = _variable_setter(75)
    var_76 = _variable_setter(76)
    var_77 = _variable_setter(77)
    var_78 = _variable_setter(78)
    var_79 = _variable_setter(79)
    var_80 = _variable_setter(80)
    var_81 = _variable_setter(81)
    var_82 = _variable_setter(82)
    var_83 = _variable_setter(83)
    var_84 = _variable_setter(84)
    var_85 = _variable_setter(85)
    var_86 = _variable_setter(86)
    var_87 = _variable_setter(87)
    var_88 = _variable_setter(88)
    var_89 = _variable_setter(89)
    var_90 = _variable_setter(90)
    var_91 = _variable_setter(91)
    var_92 = _variable_setter(92)
    var_93 = _variable_setter(93)
    var_94 = _variable_setter(94)
    var_95 = _variable_setter(95)
    var_96 = _variable_setter(96)
    var_97 = _variable_setter(97)
    var_98 = _variable_setter(98)
    var_99 = _variable_setter(99)
    var_100 = _variable_setter(100)
    var_101 = _variable_setter(101)
    var_102 = _variable_setter(102)
    var_103 = _variable_setter(103)
    var_104 = _variable_setter(104)
    var_105 = _variable_setter(105)
    var_106 = _variable_setter(106)
    var_107 = _variable_setter(107)
    var_108 = _variable_setter(108)
    var_109 = _variable_setter(109)
    var_110 = _variable_setter(110)
    var_111 = _variable_setter(111)
    var_112 = _variable_setter(112)
    var_113 = _variable_setter(113)
    var_114 = _variable_setter(114)
    var_115 = _variable_setter(115)
    var_116 = _variable_setter(116)
    var_117 = _variable_setter(117)
    var_118 = _variable_setter(118)
    var_119 = _variable_setter(119)
    var_120 = _variable_setter(120)
    var_121 = _variable_setter(121)
    var_122 = _variable_setter(122)
    var_123 = _variable_setter(123)
    var_124 = _variable_setter(124)
    var_125 = _variable_setter(125)
    var_126 = _variable_setter(126)
    var_127 = _variable_setter(127)

    commands = {
        'SETVAR': set_var, 'GETVARS': get_vars, 'READVAR': read_variable,
        'VAR_0': var_0, 'VAR_1': var_1, 'VAR_2': var_2, 'VAR_3': var_3, 'VAR_4': var_4, 'VAR_5': var_5, 'VAR_6': var_6, 'VAR_7': var_7,
        'VAR_8': var_8, 'VAR_9': var_9, 'VAR_10': var_10, 'VAR_11': var_11, 'VAR_12': var_12, 'VAR_13': var_13, 'VAR_14': var_14, 'VAR_15': var_15,
        'VAR_16': var_16, 'VAR_17': var_17, 'VAR_18': var_18, 'VAR_19': var_19, 'VAR_20': var_20, 'VAR_21': var_21, 'VAR_22': var_22, 'VAR_23': var_23,
        'VAR_24': var_24, 'VAR_25': var_25, 'VAR_26': var_26, 'VAR_27': var_27, 'VAR_28': var_28, 'VAR_29': var_29, 'VAR_30': var_30, 'VAR_31': var_31,
        'VAR_32': var_32, 'VAR_33': var_33, 'VAR_34': var_34, 'VAR_35': var_35, 'VAR_36': var_36, 'VAR_37': var_37, 'VAR_38': var_38, 'VAR_39': var_39,
        'VAR_40': var_40, 'VAR_41': var_41, 'VAR_42': var_42, 'VAR_43': var_43, 'VAR_44': var_44, 'VAR_45': var_45, 'VAR_46': var_46, 'VAR_47': var_47,
        'VAR_48': var_48, 'VAR_49': var_49, 'VAR_50': var_50, 'VAR_51': var_51, 'VAR_52': var_52, 'VAR_53': var_53, 'VAR_54': var_54, 'VAR_55': var_55,
        'VAR_56': var_56, 'VAR_57': var_57, 'VAR_58': var_58, 'VAR_59': var_59, 'VAR_60': var_60, 'VAR_61': var_61, 'VAR_62': var_62, 'VAR_63': var_63,
        'VAR_64': var_64, 'VAR_65': var_65, 'VAR_66': var_66, 'VAR_67': var_67, 'VAR_68': var_68, 'VAR_69': var_69, 'VAR_70': var_70, 'VAR_71': var_71,
        'VAR_72': var_72, 'VAR_73': var_73, 'VAR_74': var_74, 'VAR_75': var_75, 'VAR_76': var_76, 'VAR_77': var_77, 'VAR_78': var_78, 'VAR_79': var_79,
        'VAR_80': var_80, 'VAR_81': var_81, 'VAR_82': var_82, 'VAR_83': var_83, 'VAR_84': var_84, 'VAR_85': var_85, 'VAR_86': var_86, 'VAR_87': var_87,
        'VAR_88': var_88, 'VAR_89': var_89, 'VAR_90': var_90, 'VAR_91': var_91, 'VAR_92': var_92, 'VAR_93': var_93, 'VAR_94': var_94, 'VAR_95': var_95,
        'VAR_96': var_96, 'VAR_97': var_97, 'VAR_98': var_98, 'VAR_99': var_99, 'VAR_100': var_100, 'VAR_101': var_101, 'VAR_102': var_102, 'VAR_103': var_103,
        'VAR_104': var_104, 'VAR_105': var_105, 'VAR_106': var_106, 'VAR_107': var_107, 'VAR_108': var_108, 'VAR_109': var_109, 'VAR_110': var_110, 'VAR_111': var_111,
        'VAR_112': var_112, 'VAR_113': var_113, 'VAR_114': var_114, 'VAR_115': var_115, 'VAR_116': var_116, 'VAR_117': var_117, 'VAR_118': var_118, 'VAR_119': var_119,
        'VAR_120': var_120, 'VAR_121': var_121, 'VAR_122': var_122, 'VAR_123': var_123, 'VAR_124': var_124, 'VAR_125': var_125, 'VAR_126': var_126, 'VAR_127': var_127,
    }
