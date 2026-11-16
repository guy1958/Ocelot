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
    '''
    id = 'cpuxavar'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 25},
        {'driver': 'VAR_NUM', 'value': 0, 'uom': 107},
        {'driver': 'VAR_VAL', 'value': 0, 'uom': 108},
        {'driver': 'READ_RESULT', 'value': 0, 'uom': 25},
        {'driver': 'READ_VAR', 'value': 0, 'uom': 107},
        {'driver': 'READ_VAL', 'value': 0, 'uom': 108},
    ]

    def __init__(self, polyglot, primary, address, name, ctrl):
        super().__init__(polyglot, primary, address, name)
        self.ctrl = ctrl
        self.values = None      # last successfully read table: list of 128 ints, or None
        self.read_var = 0       # the variable shown in Read Variable / Read Value

    def set_var(self, command=None):
        try:
            vnum, value = op.parse_variable_command(command)
        except ValueError as ex:
            LOGGER.error('Variables %s: bad Write Variable parameters: %s' % (self.address, ex))
            self.setDriver('ST', 2)
            return
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

        On success the cache is replaced and Read Variable / Read Value show the selected variable.
        On failure the cache and the shown value are left as they were and Last Read Result says so.
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
        self.show_selected()
        log = LOGGER.debug if quiet else LOGGER.info
        log('Variables %s: read %d variables, %d non-zero' % (self.address, len(self.values), sum(1 for v in self.values if v)))
        return True

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

    commands = {'SETVAR': set_var, 'GETVARS': get_vars, 'READVAR': read_variable}
