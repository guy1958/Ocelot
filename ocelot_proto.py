'''Pure protocol helpers for the Applied Digital CPU-XA / Ocelot serial protocol.

Source: Applied Digital, CPU-XA Protocol document (3 March 2000), published at
http://www.appdig.com/Serprot/serprot.html. Nothing here touches the hub.

Not documented in that source, so deliberately not asserted here: the serial
settings (baud/parity) and the CRC algorithm on the 42-type responses (the CRC
bytes are read and ignored). The Get Variables frame is also not in that document:
it was supplied by the installer and checked on a real Ocelot (see FRAME_GET_VARIABLES).

I/O is read two ways: Get Latched I/O (command 50, used for SECU-16 and SECU-16I) and Get Real Time
I/O (a 42-type frame, used for RLY08-XA). See io_source_for_unit().
'''
import re
import threading
import time

LOCK = threading.RLock()
READ_DEADLINE = 2.0

ACK = (6, 0, 6)

TYPE_SECU16 = 11
TYPE_SECU16I = 12
TYPE_RLY08XA = 13
# Observed on a real Ocelot with one SECU-16IR installed (the protocol text does
# not list type codes): that module reported type code 6.
TYPE_SECU16IR = 6
# Observed, not documented: a real Ocelot reported 254 for every unit slot
# beyond its installed modules. It is treated as "nothing installed here".
TYPE_EMPTY_SLOT = 254

# Which read supplies a module's I/O data.
SOURCE_LATCHED = 'latched'
SOURCE_REALTIME = 'realtime'

CMD_GET_LATCHED_IO = 50
CMD_WRITE_VARIABLE = 41
CMD_SEND_RESIDENT_IR = 90
CMD_SEND_REMOTE_IR = 92
ZONE_ALL = 255
IR_ZONES = 16
# Highest IR number accepted for SECU-16IR zones, as stated by the installer. The
# protocol itself carries a 16-bit number.
IR_NUMBER_MAX = 1023
# Highest resident IR number, per the protocol document ("IRnumber (0 to 39)").
RESIDENT_IR_MAX = 39
# Write CPUXA Variable Data: data is a 16-bit value, LSB first. The variable number
# range 0-127 is as stated by the installer (versions up to 1.8.1 used 0-63, which is
# what the March 2000 protocol document lists: 0-60 regular, 61 Leopard beep counter,
# 62 time conversion, 63 Leopard screen number). Whether 61-63 are still special on
# hardware with 128 variables is not documented. The document does not say whether the
# value is signed; it is sent as unsigned.
VARIABLE_MAX = 127
VARIABLE_COUNT = VARIABLE_MAX + 1
VARIABLE_VALUE_MAX = 65535

# Settings added after 1.0: older installs do not have them in their saved config.
SEED_PARAM_KEYS = ('IPAddress', 'IPPort')
# Settings that no longer exist: Port (removed 1.6.0), X10Devices (removed 1.7.0 with X-10 support),
# Baud (removed 1.8.0).
OBSOLETE_PARAM_KEYS = ('Port', 'X10Devices', 'Baud')
# Of those, the ones whose value is superseded once IPAddress is set.
SUPERSEDED_BY_IP = ('Port',)
# Of those, the ones whose value never had any effect, so any value may be deleted.
IGNORED_VALUE_KEYS = ('Baud',)

# Fixed read frames. FRAME_GET_LATCHED_IO, FRAME_GET_REALTIME_IO and FRAME_GET_UNIT_TYPE are
# exactly as published in the protocol document.
# Get Latched I/O: a 200-type frame (command 50, checksum 250). Reply: 3-byte header 6,0,6, then
# 256 data bytes (no 6-byte header and no CRC, unlike the 42-type reads). Not yet checked on hardware.
FRAME_GET_LATCHED_IO = bytes([200, 50, 0, 0, 0, 0, 0, 250])
FRAME_GET_REALTIME_IO = bytes([42, 0, 0, 141, 181, 0, 37, 233])
FRAME_GET_UNIT_TYPE = bytes([42, 0, 0, 1, 176, 0, 148, 39])
# Get Variables: NOT in the protocol document. Supplied by the installer and tested on a real
# Ocelot, which answered with 264 bytes: a 6-byte header equal to the first six bytes of this
# request (2a 00 00 91 aa 00), 256 data bytes and 2 trailer bytes (CRC, not interpreted).
# The last two request bytes cannot be computed here, so the frame is sent as given.
# The data is 128 variables of 16 bits each, LSB first: variable n is data[2n] | data[2n+1] << 8
# (confirmed on that Ocelot: variable 58 = 999 and variable 59 = 1001 were at data bytes 116-119
# as e7 03 e9 03).
FRAME_GET_VARIABLES = bytes([42, 0, 0, 145, 170, 0, 0, 166])
GET_VARIABLES_HEADER = tuple(FRAME_GET_VARIABLES[:6])

_HOST_LABEL = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')
_PORT_NUMBER = re.compile(r'^[0-9]{1,5}$')


def valid_host(host):
    '''True for a dotted-quad IPv4 address or a plain DNS host name (IPv6 is not supported).'''
    if not host or len(host) > 253:
        return False
    if re.match(r'^[0-9.]+$', host):
        parts = host.split('.')
        return len(parts) == 4 and all(p.isdigit() and len(p) <= 3 and 0 <= int(p) <= 255 for p in parts)
    return all(_HOST_LABEL.match(label) for label in host.split('.'))


def resolve_port(params):
    '''Work out what to open from the saved settings. Returns (port, error); exactly one is None.

    Only IPAddress + IPPort are used, giving socket://IPAddress:IPPort. The removed Port setting is
    ignored when IPAddress is set; if it is the only thing configured, the error says it is gone.
    '''
    params = params or {}

    def get(key):
        return str(params.get(key, '') or '').strip()

    ip, ipport, legacy = get('IPAddress'), get('IPPort'), get('Port')
    if ip:
        if not valid_host(ip):
            return None, ('IPAddress "%s" is not a valid IPv4 address or host name. Enter just the address, '
                          'for example 192.168.0.70 (no socket:// prefix and no :port).' % ip)
        if not ipport:
            return None, 'IPAddress is set but IPPort is empty. Enter the TCP port of the serial-to-Ethernet adapter, for example 3001.'
        if not _PORT_NUMBER.match(ipport) or not 1 <= int(ipport) <= 65535:
            return None, 'IPPort must be a whole number from 1 to 65535, not "%s".' % ipport
        return 'socket://%s:%d' % (ip, int(ipport)), None
    if ipport:
        return None, 'IPPort is set but IPAddress is empty. Enter the IP address or host name of the serial-to-Ethernet adapter.'
    if legacy:
        return None, ('The Port setting was removed in version 1.6.0. Enter the serial-to-Ethernet adapter\'s '
                      'IPAddress and IPPort instead (the old Port value was "%s").' % legacy)
    return None, 'Set IPAddress and IPPort (the serial-to-Ethernet adapter) in the plugin configuration.'


def missing_param_keys(params):
    '''Keys from SEED_PARAM_KEYS absent from a non-empty saved config (so they can be added empty).

    An empty config is left alone: there is nothing of the user's to preserve and PG3 seeds its own defaults.
    '''
    if not params:
        return []
    return [k for k in SEED_PARAM_KEYS if k not in params]


def obsolete_param_keys(params):
    '''Removed settings still in the saved config that are safe to delete.

    An empty entry is always safe. A Port that holds a value is also safe once IPAddress is set (the
    value is superseded), and Baud is safe with any value. Anything else that still holds a value is
    kept so it is never silently lost: a Port with no IPAddress (resolve_port() explains what to do)
    and any X10Devices list (there is no replacement for X-10 support; discover() shows a notice).
    '''
    params = params or {}
    ip = str(params.get('IPAddress', '') or '').strip()
    out = []
    for key in OBSOLETE_PARAM_KEYS:
        if key not in params:
            continue
        empty = not str(params.get(key, '') or '').strip()
        superseded = bool(ip) and key in SUPERSEDED_BY_IP
        if empty or superseded or key in IGNORED_VALUE_KEYS:
            out.append(key)
    return out


def checksum(values):
    return sum(values) & 0xFF


def build_frame(cmd, p1=0, p2=0, p3=0, p4=0, p5=0):
    body = [200, cmd, p1, p2, p3, p4, p5]
    return bytes(body + [checksum(body)])


def open_port(port, timeout=1.0):
    import serial
    # pyserial's API needs a baud value; for socket:// it is ignored (the adapter sets the real one)
    return serial.serial_for_url(port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=timeout)


def read_exact(ser, n):
    buf = bytearray()
    end = time.monotonic() + READ_DEADLINE
    while len(buf) < n and time.monotonic() < end:
        chunk = ser.read(n - len(buf))
        if chunk:
            buf.extend(chunk)
        else:
            time.sleep(0.01)
    return bytes(buf)


def _send(ser, frame):
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    ser.write(frame)
    try:
        ser.flush()
    except Exception:
        pass


def send_command(ser, frame):
    '''Send a frame and return True if the Ocelot answered with the 6,0,6 acknowledgement.'''
    with LOCK:
        _send(ser, frame)
        return tuple(read_exact(ser, 3)) == ACK


def read_block(ser, frame, header_len, trailer_len=0, expect_header=None):
    '''Send a frame and return the 256 data bytes of the reply, or None on a short/bad reply.'''
    with LOCK:
        _send(ser, frame)
        raw = read_exact(ser, header_len + 256 + trailer_len)
    if len(raw) < header_len + 256:
        return None
    if expect_header is not None and tuple(raw[:header_len]) != tuple(expect_header):
        return None
    return raw[header_len:header_len + 256]


def get_realtime_io(ser):
    return read_block(ser, FRAME_GET_REALTIME_IO, 6, 2)


def get_latched_io(ser):
    '''Send Get Latched I/O and return the 256 data bytes, or None on a short reply or a header other than 6,0,6.

    Reading the latched data clears the latches (stated by the installer; the document does not say).
    '''
    return read_block(ser, FRAME_GET_LATCHED_IO, 3, 0, expect_header=ACK)


def get_unit_types(ser):
    return read_block(ser, FRAME_GET_UNIT_TYPE, 6, 2)


def get_variables(ser):
    '''Send Get Variables and return the 256 data bytes, or None on a short reply or a wrong header.'''
    return read_block(ser, FRAME_GET_VARIABLES, 6, 2, expect_header=GET_VARIABLES_HEADER)


def parse_variables(data):
    '''Turn the 256 data bytes of a Get Variables reply into a list of 128 values (LSB first).

    Raises ValueError if fewer than 256 bytes are given.
    '''
    if data is None or len(data) < 2 * VARIABLE_COUNT:
        raise ValueError('Get Variables data must be %d bytes' % (2 * VARIABLE_COUNT))
    return [data[2 * n] | (data[2 * n + 1] << 8) for n in range(VARIABLE_COUNT)]


def parse_unit_types(data):
    '''Map unit number (1-based) -> type code for the first 128 bytes; zero means no unit.'''
    return {i + 1: data[i] for i in range(128) if data[i]}


def io_source_for_unit(unit_type):
    '''Which read supplies this unit type's I/O data, or None for a type without I/O points.

    SECU-16 and SECU-16I use Get Latched I/O (installer's choice, 1.13.0); RLY08-XA stays on Get Real
    Time I/O. The document describes an RLY08-XA latched layout with the relays in the second byte,
    which contradicts what was measured on a real RLY08-XA (first byte), so that unit is not moved.
    '''
    if unit_type in (TYPE_SECU16, TYPE_SECU16I):
        return SOURCE_LATCHED
    if unit_type == TYPE_RLY08XA:
        return SOURCE_REALTIME
    return None


def points_for_unit(unit_type):
    '''Return [(kind, index, byte, bit)] for a unit type; byte 0 is Data1, byte 1 is Data2.

    Layouts (the same positions in the latched and the real-time reply for SECU-16 and SECU-16I):
      SECU-16   inputs in Data1, relays in Data2. Confirmed by the installer on real hardware
                (reported working, read with Get Real Time I/O). The protocol document gives the same
                layout for Get Latched I/O.
      SECU-16I  16 inputs, Data1 then Data2. Not confirmed on hardware (the document gives this layout).
      RLY08-XA  8 relays in Data1 (bit n = relay n), Data2 unused. Confirmed on a real unit by
                switching relay 7: bit 7 of Data1 followed it and Data2 stayed 0. Versions up to
                1.8.0 read Data2, so these relays always showed Off.
    '''
    pts = []
    if unit_type == TYPE_SECU16:
        pts += [('input', i, 0, i) for i in range(8)]
        pts += [('relay', i, 1, i) for i in range(8)]
    elif unit_type == TYPE_SECU16I:
        pts += [('input', i, 0 if i < 8 else 1, i % 8) for i in range(16)]
    elif unit_type == TYPE_RLY08XA:
        pts += [('relay', i, 0, i) for i in range(8)]
    return pts


def classify_units(types):
    '''Split {unit: type_code} into (supported, unsupported, empty).

    supported   -- {unit: type_code} for types this plugin builds nodes for
                   (I/O modules with points, and SECU-16IR IR modules)
    unsupported -- {unit: type_code} for any other code except the empty-slot marker; each one
                   gets a placeholder node (see placeholder_name())
    empty       -- sorted list of units reporting the empty-slot marker (254)
    '''
    supported, unsupported, empty = {}, {}, []
    for unit, utype in sorted(types.items()):
        if points_for_unit(utype) or utype == TYPE_SECU16IR:
            supported[unit] = utype
        elif utype == TYPE_EMPTY_SLOT:
            empty.append(unit)
        else:
            unsupported[unit] = utype
    return supported, unsupported, empty


def placeholder_name(unit, unit_type):
    '''Node name of the placeholder for an unsupported module: 'Mod <unit> Type <type code>'.'''
    return 'Mod %d Type %d' % (unit, unit_type)


def placeholder_address(unit, unit_type):
    '''Node address of that placeholder, 'u<unit>t<type code>' (at most 8 characters for units 1-128, types 0-255).

    The type is part of the address so the name and the address always agree: a unit that later
    reports a different type gets a new placeholder instead of a stale name.
    '''
    return 'u%dt%d' % (unit, unit_type)


def get_bit(data, unit, byte, bit):
    return (data[2 * (unit - 1) + byte] >> bit) & 1


def write_relay(ser, unit, relay, on):
    if not (0 < unit <= 128 and 0 <= relay <= 7):
        raise ValueError('unit must be 1-128 and relay 0-7')
    return send_command(ser, build_frame(51, unit, relay, 1 if on else 0))


def build_variable_write(vnum, value):
    '''Frame for Write CPUXA Variable Data: 200, 41, vnum, LSB, MSB, 0, 0, csum.'''
    if not 0 <= vnum <= VARIABLE_MAX:
        raise ValueError('variable number must be 0-%d' % VARIABLE_MAX)
    if not 0 <= value <= VARIABLE_VALUE_MAX:
        raise ValueError('variable value must be 0-%d' % VARIABLE_VALUE_MAX)
    return build_frame(CMD_WRITE_VARIABLE, vnum, value & 0xFF, value >> 8)


def write_variable(ser, vnum, value):
    return send_command(ser, build_variable_write(vnum, value))


def _named_params(command):
    '''Map upper-cased parameter names to values from a command dict.

    PG3 delivers named parameters in command['query'] with keys like 'VARNUM.uom107'.
    '''
    query = (command or {}).get('query') or {}
    found = {}
    for key, value in query.items():
        found[str(key).split('.')[0].upper()] = value
    return found


def parse_variable_command(command):
    '''Extract (vnum, value) from a Write Variable command dict. Raises ValueError if missing/invalid.'''
    found = _named_params(command)
    out = []
    for name, top in (('VARNUM', VARIABLE_MAX), ('VALUE', VARIABLE_VALUE_MAX)):
        if name not in found:
            raise ValueError('missing parameter %s' % name)
        try:
            n = int(float(found[name]))
        except (TypeError, ValueError):
            raise ValueError('%s is not a number: %r' % (name, found[name]))
        if not 0 <= n <= top:
            raise ValueError('%s must be 0-%d, got %d' % (name, top, n))
        out.append(n)
    return out[0], out[1]


def parse_variable_number(command):
    '''Extract the variable number (0-127) from a Read Variable command dict. Raises ValueError otherwise.'''
    found = _named_params(command)
    if 'VARNUM' not in found:
        raise ValueError('missing parameter VARNUM')
    try:
        n = int(float(found['VARNUM']))
    except (TypeError, ValueError):
        raise ValueError('VARNUM is not a number: %r' % (found['VARNUM'],))
    if not 0 <= n <= VARIABLE_MAX:
        raise ValueError('VARNUM must be 0-%d, got %d' % (VARIABLE_MAX, n))
    return n


def build_remote_ir(mnum, znum, irnum):
    '''Frame for Send Remote IR Command: 200, 92, mnum, znum, IRlo, IRhi, 0, csum.

    mnum is the SECU-16IR unit (1-128), znum the zone (0-15, or 255 for all
    zones), irnum the previously learned IR number as a 16-bit value.
    '''
    if not 1 <= mnum <= 128:
        raise ValueError('IR module unit must be 1-128')
    if not (0 <= znum <= 15 or znum == ZONE_ALL):
        raise ValueError('IR zone must be 0-15, or 255 for all zones')
    if not 0 <= irnum <= 65535:
        raise ValueError('IR number must be 0-65535')
    return build_frame(CMD_SEND_REMOTE_IR, mnum, znum, irnum & 0xFF, irnum >> 8)


def send_remote_ir(ser, mnum, znum, irnum):
    return send_command(ser, build_remote_ir(mnum, znum, irnum))


def build_resident_ir(irnum):
    '''Frame for Send Resident IR: 200, 90, LSB, MSB, 0, 0, 0, csum.

    The Ocelot sends the IR command stored under irnum (0-39 per the protocol
    document) through its own IR output.
    '''
    if not 0 <= irnum <= RESIDENT_IR_MAX:
        raise ValueError('resident IR number must be 0-%d' % RESIDENT_IR_MAX)
    return build_frame(CMD_SEND_RESIDENT_IR, irnum & 0xFF, irnum >> 8)


def send_resident_ir(ser, irnum):
    return send_command(ser, build_resident_ir(irnum))


def parse_ir_number(command, max_num=IR_NUMBER_MAX):
    '''Extract the IR number from a Send IR command dict (0-max_num). Raises ValueError otherwise.

    PG3 delivers named parameters in command['query'] with keys like 'IRNUM.uom108'.
    '''
    found = _named_params(command)
    if 'IRNUM' not in found:
        raise ValueError('missing parameter IRNUM')
    try:
        irnum = int(float(found['IRNUM']))
    except (TypeError, ValueError):
        raise ValueError('IRNUM is not a number: %r' % (found['IRNUM'],))
    if not 0 <= irnum <= max_num:
        raise ValueError('IR number must be 0-%d, got %d' % (max_num, irnum))
    return irnum


def rescan(ser):
    return send_command(ser, build_frame(32))
