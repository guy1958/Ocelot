import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ocelot_proto as op

op.READ_DEADLINE = 0.05


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


class ProtoTests(unittest.TestCase):
    def test_checksums_match_published_frames(self):
        # Complete frames published in the Applied Digital protocol document.
        for cmd, csum in {32: 232, 50: 250, 52: 252, 54: 254, 62: 6, 56: 0}.items():
            frame = op.build_frame(cmd)
            self.assertEqual(len(frame), 8)
            self.assertEqual(frame[0], 200)
            self.assertEqual(frame[-1], csum, 'cmd %d' % cmd)

    def test_write_relay_frame_and_ack(self):
        ser = FakeSer(bytes([6, 0, 6]))
        self.assertTrue(op.write_relay(ser, 3, 5, True))
        self.assertEqual(ser.written[0], bytes([200, 51, 3, 5, 1, 0, 0, (200 + 51 + 3 + 5 + 1) & 255]))

    def test_no_ack_is_false(self):
        self.assertFalse(op.write_relay(FakeSer(b''), 1, 0, False))

    def test_write_relay_range_check(self):
        with self.assertRaises(ValueError):
            op.write_relay(FakeSer(), 0, 0, True)
        with self.assertRaises(ValueError):
            op.write_relay(FakeSer(), 1, 8, True)

    def test_points_for_unit(self):
        p11 = op.points_for_unit(11)
        self.assertEqual(len([p for p in p11 if p[0] == 'input']), 8)
        self.assertEqual(len([p for p in p11 if p[0] == 'relay']), 8)
        p12 = op.points_for_unit(12)
        self.assertEqual(len(p12), 16)
        self.assertIn(('input', 9, 1, 1), p12)
        p13 = op.points_for_unit(13)
        self.assertEqual([p[0] for p in p13], ['relay'] * 8)
        self.assertEqual(op.points_for_unit(99), [])
        self.assertEqual(op.points_for_unit(op.TYPE_SECU16IR), [])

    def test_rly08xa_relays_are_in_first_byte(self):
        # Measured on a real RLY08-XA (unit 3): its first data byte read 152 = 0b10011000 with relays
        # 3, 4 and 7 on, then 24 after relay 7 was switched off; the second byte stayed 0.
        # Versions up to 1.8.0 read the second byte, so every relay showed Off.
        pts = op.points_for_unit(op.TYPE_RLY08XA)
        self.assertEqual([(k, i, b, bit) for k, i, b, bit in pts], [('relay', i, 0, i) for i in range(8)])
        data = bytearray(256)
        data[2 * (3 - 1)] = 152
        self.assertEqual([op.get_bit(data, 3, b, bit) for _, _, b, bit in pts], [0, 0, 0, 1, 1, 0, 0, 1])
        data[2 * (3 - 1)] = 24
        self.assertEqual([op.get_bit(data, 3, b, bit) for _, _, b, bit in pts], [0, 0, 0, 1, 1, 0, 0, 0])
        # a unit's two bytes belong to that unit only: unit 2's bytes do not leak into unit 3's relays
        data = bytearray(256)
        data[2], data[3] = 255, 255
        self.assertEqual([op.get_bit(data, 3, b, bit) for _, _, b, bit in pts], [0] * 8)

    def test_secu16_layout(self):
        # Confirmed by the installer on real hardware (reported working): inputs in Data1, relays in Data2.
        p11 = op.points_for_unit(op.TYPE_SECU16)
        self.assertTrue(all(b == 0 for k, i, b, bit in p11 if k == 'input'))
        self.assertTrue(all(b == 1 for k, i, b, bit in p11 if k == 'relay'))

    def test_get_bit_and_unit_types(self):
        data = bytearray(256)
        data[2 * (2 - 1) + 1] = 0b00000100
        self.assertEqual(op.get_bit(data, 2, 1, 2), 1)
        self.assertEqual(op.get_bit(data, 2, 1, 3), 0)
        types = bytearray(256)
        types[0] = 11
        types[2] = 13
        self.assertEqual(op.parse_unit_types(types), {1: 11, 3: 13})

    def test_classify_units_real_hardware_shape(self):
        # Shape reported by a real Ocelot: units 1,2 = 11, unit 3 = 13, unit 4 = 6 (SECU-16IR), rest 254.
        data = bytearray([254] * 256)
        data[0], data[1], data[2], data[3] = 11, 11, 13, 6
        types = op.parse_unit_types(data)
        supported, unsupported, empty = op.classify_units(types)
        self.assertEqual(supported, {1: 11, 2: 11, 3: 13, 4: 6})
        self.assertEqual(unsupported, {})
        self.assertEqual(empty, list(range(5, 129)))

    def test_classify_units_unknown_type_is_unsupported(self):
        supported, unsupported, empty = op.classify_units({1: 11, 2: 77, 3: 254})
        self.assertEqual(supported, {1: 11})
        self.assertEqual(unsupported, {2: 77})
        self.assertEqual(empty, [3])

    def test_classify_units_empty_input(self):
        self.assertEqual(op.classify_units({}), ({}, {}, []))

    def test_build_remote_ir_frame(self):
        # <200> <92> <mnum> <znum> <IRlo> <IRhi> <0> <csum>; IR 300 = hi 1, lo 44
        frame = op.build_remote_ir(4, 3, 300)
        self.assertEqual(frame, bytes([200, 92, 4, 3, 44, 1, 0, (200 + 92 + 4 + 3 + 44 + 1) & 255]))
        all_zones = op.build_remote_ir(128, 255, 0)
        self.assertEqual(all_zones, bytes([200, 92, 128, 255, 0, 0, 0, (200 + 92 + 128 + 255) & 255]))
        self.assertEqual(op.build_remote_ir(1, 15, 65535)[4:6], bytes([255, 255]))
        # Top of the plugin's accepted range: 1023 = hi 3, lo 255
        self.assertEqual(op.build_remote_ir(4, 15, 1023)[2:6], bytes([4, 15, 255, 3]))

    def test_build_remote_ir_range_checks(self):
        for args in [(0, 0, 0), (129, 0, 0), (4, 16, 0), (4, 254, 0), (4, -1, 0), (4, 0, -1), (4, 0, 65536)]:
            with self.assertRaises(ValueError, msg=str(args)):
                op.build_remote_ir(*args)

    def test_send_remote_ir_ack(self):
        ser = FakeSer(bytes([6, 0, 6]))
        self.assertTrue(op.send_remote_ir(ser, 4, 2, 7))
        self.assertEqual(ser.written[0], op.build_remote_ir(4, 2, 7))
        self.assertFalse(op.send_remote_ir(FakeSer(b''), 4, 2, 7))

    def test_every_zone_frame_is_distinct(self):
        frames = {op.build_remote_ir(4, z, 5) for z in range(op.IR_ZONES)}
        self.assertEqual(len(frames), 16)

    def test_build_resident_ir_frame(self):
        # <200> <90> <LSB> <MSB> <0> <0> <0> <csum>, csum = 200 + 90 + LSB + MSB
        self.assertEqual(op.build_resident_ir(0), bytes([200, 90, 0, 0, 0, 0, 0, (200 + 90) & 255]))
        self.assertEqual(op.build_resident_ir(5), bytes([200, 90, 5, 0, 0, 0, 0, (200 + 90 + 5) & 255]))
        self.assertEqual(op.build_resident_ir(39), bytes([200, 90, 39, 0, 0, 0, 0, (200 + 90 + 39) & 255]))

    def test_build_resident_ir_range_checks(self):
        for n in (-1, 40, 1023, 65535):
            with self.assertRaises(ValueError, msg=str(n)):
                op.build_resident_ir(n)

    def test_send_resident_ir_ack(self):
        ser = FakeSer(bytes([6, 0, 6]))
        self.assertTrue(op.send_resident_ir(ser, 12))
        self.assertEqual(ser.written[0], op.build_resident_ir(12))
        self.assertFalse(op.send_resident_ir(FakeSer(b''), 12))

    def test_resident_and_remote_frames_differ(self):
        self.assertNotEqual(op.build_resident_ir(5)[1], op.build_remote_ir(1, 0, 5)[1])
        self.assertEqual((op.build_resident_ir(5)[1], op.build_remote_ir(1, 0, 5)[1]), (90, 92))

    def test_variable_limits(self):
        # Variable numbers 0-127 as stated by the installer (1.8.1 and earlier used 0-63); values 0-65535.
        self.assertEqual(op.VARIABLE_MAX, 127)
        self.assertEqual(op.VARIABLE_COUNT, 128)
        self.assertEqual(op.VARIABLE_VALUE_MAX, 65535)

    def test_build_variable_write_frame(self):
        # <200> <41> <vnum> <LSB data> <MSB data> <0> <0> <csum>; csum = 200 + 41 + vnum + LSB + MSB
        self.assertEqual(op.build_variable_write(5, 300), bytes([200, 41, 5, 44, 1, 0, 0, (200 + 41 + 5 + 44 + 1) & 255]))
        self.assertEqual(op.build_variable_write(0, 0), bytes([200, 41, 0, 0, 0, 0, 0, (200 + 41) & 255]))
        self.assertEqual(op.build_variable_write(63, 65535), bytes([200, 41, 63, 255, 255, 0, 0, (200 + 41 + 63 + 255 + 255) & 255]))
        # the widened range: 64 and 127 are now accepted and sent as the plain variable number byte
        self.assertEqual(op.build_variable_write(64, 1), bytes([200, 41, 64, 1, 0, 0, 0, (200 + 41 + 64 + 1) & 255]))
        self.assertEqual(op.build_variable_write(127, 65535), bytes([200, 41, 127, 255, 255, 0, 0, (200 + 41 + 127 + 255 + 255) & 255]))
        # 256 = LSB 0, MSB 1 (byte order check)
        self.assertEqual(op.build_variable_write(60, 256)[2:5], bytes([60, 0, 1]))

    def test_build_variable_write_range_checks(self):
        for args in [(-1, 0), (128, 0), (255, 0), (0, -1), (0, 65536)]:
            with self.assertRaises(ValueError, msg=str(args)):
                op.build_variable_write(*args)

    def test_write_variable_ack(self):
        ser = FakeSer(bytes([6, 0, 6]))
        self.assertTrue(op.write_variable(ser, 10, 1234))
        self.assertEqual(ser.written[0], op.build_variable_write(10, 1234))
        self.assertFalse(op.write_variable(FakeSer(b''), 10, 1234))

    def test_variable_frame_differs_from_ir_frames(self):
        self.assertEqual({op.build_variable_write(1, 1)[1], op.build_resident_ir(1)[1], op.build_remote_ir(1, 0, 1)[1]}, {41, 90, 92})

    def test_parse_variable_command(self):
        cmd = {'cmd': 'SETVAR', 'query': {'VARNUM.uom107': '12', 'VALUE.uom108': '4000'}}
        self.assertEqual(op.parse_variable_command(cmd), (12, 4000))
        self.assertEqual(op.parse_variable_command({'query': {'varnum': 127, 'value': '65535.0'}}), (127, 65535))
        self.assertEqual(op.parse_variable_command({'query': {'VARNUM': 64, 'VALUE': 7}}), (64, 7))
        self.assertEqual(op.parse_variable_command({'query': {'VARNUM': 0, 'VALUE': 0}}), (0, 0))

    def test_parse_variable_command_rejects_bad_input(self):
        for cmd in [{'query': {'VARNUM': 128, 'VALUE': 1}}, {'query': {'VARNUM': -1, 'VALUE': 1}},
                    {'query': {'VARNUM': 1, 'VALUE': 65536}}, {'query': {'VARNUM': 1, 'VALUE': -5}},
                    {'query': {'VARNUM': 'x', 'VALUE': 1}}, {'query': {'VARNUM': 1}},
                    {'query': {'VALUE': 1}}, {'cmd': 'SETVAR'}, None]:
            with self.assertRaises(ValueError, msg=str(cmd)):
                op.parse_variable_command(cmd)

    # ---- Get Variables / Read Variable (1.9.0) ----

    def test_get_variables_frame(self):
        # Supplied by the installer, tested on a real Ocelot: 42,0,0,145,170,0,0,166.
        self.assertEqual(op.FRAME_GET_VARIABLES, bytes([42, 0, 0, 145, 170, 0, 0, 166]))
        self.assertEqual(op.FRAME_GET_VARIABLES.hex(' '), '2a 00 00 91 aa 00 00 a6')
        self.assertEqual(op.GET_VARIABLES_HEADER, (42, 0, 0, 145, 170, 0))
        # a read frame like the other two (starts with 42), not a 200-type write frame
        self.assertEqual(op.FRAME_GET_VARIABLES[0], 42)
        self.assertNotEqual(op.FRAME_GET_VARIABLES, op.FRAME_GET_REALTIME_IO)
        self.assertNotEqual(op.FRAME_GET_VARIABLES, op.FRAME_GET_UNIT_TYPE)

    def test_parse_variables_is_lsb_first(self):
        # Confirmed on hardware: variable 58 = 999 and 59 = 1001 sat at data bytes 116-119 as e7 03 e9 03.
        data = bytearray(256)
        data[116:120] = bytes([0xE7, 0x03, 0xE9, 0x03])
        vals = op.parse_variables(bytes(data))
        self.assertEqual(len(vals), 128)
        self.assertEqual(vals[58], 999)
        self.assertEqual(vals[59], 1001)
        self.assertEqual(sum(1 for v in vals if v), 2)
        # byte order: first byte is the LOW byte
        data = bytearray(256)
        data[0], data[1] = 0x01, 0x02
        data[254], data[255] = 0xFF, 0xFF
        vals = op.parse_variables(bytes(data))
        self.assertEqual(vals[0], 0x0201)
        self.assertEqual(vals[127], 65535)

    def test_parse_variables_real_capture_shape(self):
        # The non-zero bytes of a real Get Variables reply (data bytes, i.e. reply offset - 6).
        data = bytearray(256)
        data[14] = 1
        data[116:120] = bytes.fromhex('e703e903')
        data[126] = 1
        data[240:256] = bytes.fromhex('0b0401000000060025001100' + '0f000000')
        vals = op.parse_variables(bytes(data))
        self.assertEqual({n: v for n, v in enumerate(vals) if v},
                         {7: 1, 58: 999, 59: 1001, 63: 1, 120: 1035, 121: 1, 123: 6, 124: 37, 125: 17, 126: 15})

    def test_parse_variables_rejects_short_data(self):
        for bad in (None, b'', bytes(255), bytes(10)):
            with self.assertRaises(ValueError, msg=repr(bad)):
                op.parse_variables(bad)
        self.assertEqual(op.parse_variables(bytes(256)), [0] * 128)

    def test_get_variables_reads_and_checks_header(self):
        payload = bytearray(256)
        payload[116:120] = bytes.fromhex('e703e903')
        header = bytes([42, 0, 0, 145, 170, 0])
        ser = FakeSer(header + bytes(payload) + bytes([0, 0xC2]))
        self.assertEqual(op.get_variables(ser), bytes(payload))
        self.assertEqual(ser.written[0], op.FRAME_GET_VARIABLES)
        # the trailer is optional as far as the data goes (it is not interpreted)
        self.assertEqual(op.get_variables(FakeSer(header + bytes(payload))), bytes(payload))
        # a reply that echoes a different request (wrong header) is rejected
        wrong = bytes([42, 0, 0, 1, 176, 0])
        self.assertIsNone(op.get_variables(FakeSer(wrong + bytes(payload) + bytes(2))))
        # no reply, and a short reply
        self.assertIsNone(op.get_variables(FakeSer(b'')))
        self.assertIsNone(op.get_variables(FakeSer(header + bytes(100))))

    def test_parse_variable_number(self):
        self.assertEqual(op.parse_variable_number({'cmd': 'READVAR', 'query': {'VARNUM.uom107': '58'}}), 58)
        self.assertEqual(op.parse_variable_number({'query': {'varnum': '127.0'}}), 127)
        self.assertEqual(op.parse_variable_number({'query': {'VARNUM': 0}}), 0)

    def test_parse_variable_number_rejects_bad_input(self):
        for cmd in [{'query': {'VARNUM': 128}}, {'query': {'VARNUM': -1}}, {'query': {'VARNUM': 'x'}},
                    {'query': {'VALUE': 5}}, {'cmd': 'READVAR'}, None]:
            with self.assertRaises(ValueError, msg=str(cmd)):
                op.parse_variable_number(cmd)

    def test_valid_host(self):
        # '1.2.3.4a' is a legal DNS name (labels may start with a digit), so it is accepted
        for good in ['192.168.0.70', '0.0.0.0', '255.255.255.255', 'ocelot', 'ocelot-gw.local', 'Adapter1.example.com', 'a1', '1.2.3.4a']:
            self.assertTrue(op.valid_host(good), good)
        for bad in ['', '192.168.0.700', '192.168.0', '192.168.0.70.1', '1.2.3.', '.1.2.3', 'a..b', 'host.', '-a.com',
                    'a-.com', 'bad host', 'socket://192.168.0.70', '192.168.0.70:3001', 'host/path', 'a_b']:
            self.assertFalse(op.valid_host(bad), repr(bad))
        self.assertFalse(op.valid_host('a' * 64))
        self.assertTrue(op.valid_host('a' * 63))

    def test_resolve_port_ip_and_port(self):
        self.assertEqual(op.resolve_port({'IPAddress': '192.168.0.70', 'IPPort': '3001'}), ('socket://192.168.0.70:3001', None))
        # whitespace is trimmed; a numeric (non-string) port value is accepted
        self.assertEqual(op.resolve_port({'IPAddress': ' ocelot.local ', 'IPPort': ' 4001 '}), ('socket://ocelot.local:4001', None))
        self.assertEqual(op.resolve_port({'IPAddress': '10.0.0.5', 'IPPort': 3001}), ('socket://10.0.0.5:3001', None))
        self.assertEqual(op.resolve_port({'IPAddress': '10.0.0.5', 'IPPort': '1'}), ('socket://10.0.0.5:1', None))
        self.assertEqual(op.resolve_port({'IPAddress': '10.0.0.5', 'IPPort': '65535'}), ('socket://10.0.0.5:65535', None))

    def test_resolve_port_the_real_config(self):
        # the saved settings on the real hub, with and without the removed Baud entry
        for params in [{'Baud': '9600', 'InvertInputs': 'false', 'IPAddress': '192.168.0.70', 'IPPort': '3001'},
                       {'InvertInputs': 'false', 'IPAddress': '192.168.0.70', 'IPPort': '3001'}]:
            self.assertEqual(op.resolve_port(params), ('socket://192.168.0.70:3001', None))

    def test_resolve_port_ignores_leftover_port(self):
        # a leftover Port never overrides IPAddress/IPPort
        for leftover in ['/dev/cuaU0', 'socket://10.9.9.9:1', '']:
            params = {'IPAddress': '192.168.0.70', 'IPPort': '3001', 'Port': leftover}
            self.assertEqual(op.resolve_port(params), ('socket://192.168.0.70:3001', None), leftover)

    def test_resolve_port_old_port_alone_gives_helpful_error(self):
        port, err = op.resolve_port({'Port': 'socket://192.168.0.70:3001', 'InvertInputs': 'false'})
        self.assertIsNone(port)
        self.assertIn('removed', err)
        self.assertIn('IPAddress', err)
        self.assertIn('IPPort', err)
        self.assertIn('socket://192.168.0.70:3001', err)  # shows the old value so it is not lost
        # a serial device path is no longer connectable either
        port, err = op.resolve_port({'Port': '/dev/cuaU0', 'IPAddress': '', 'IPPort': ''})
        self.assertIsNone(port)
        self.assertIn('/dev/cuaU0', err)

    def test_resolve_port_errors(self):
        for params in [{'IPAddress': '192.168.0.70'},
                       {'IPAddress': '192.168.0.70', 'IPPort': ''},
                       {'IPAddress': '192.168.0.700', 'IPPort': '3001'},
                       {'IPAddress': 'socket://192.168.0.70', 'IPPort': '3001'},
                       {'IPAddress': '192.168.0.70:3001', 'IPPort': '3001'},
                       {'IPAddress': '192.168.0.70', 'IPPort': '0'},
                       {'IPAddress': '192.168.0.70', 'IPPort': '65536'},
                       {'IPAddress': '192.168.0.70', 'IPPort': '-1'},
                       {'IPAddress': '192.168.0.70', 'IPPort': 'abc'},
                       {'IPAddress': '192.168.0.70', 'IPPort': '30 01'},
                       {'IPAddress': '192.168.0.70', 'IPPort': '3001.0'},
                       {'IPPort': '3001'},
                       {'Port': '/dev/cuaU0', 'IPPort': '3001'},
                       {}, None, {'IPAddress': '', 'IPPort': '', 'Port': '  '}]:
            port, err = op.resolve_port(params)
            self.assertIsNone(port, str(params))
            self.assertTrue(err and isinstance(err, str), str(params))
        # an invalid IPAddress is an error even when a leftover Port is also present
        port, err = op.resolve_port({'IPAddress': '192.168.0.700', 'IPPort': '3001', 'Port': 'socket://10.9.9.9:1'})
        self.assertIsNone(port)
        self.assertIn('IPAddress', err)

    def test_resolve_port_error_messages_name_the_setting(self):
        self.assertIn('IPPort', op.resolve_port({'IPAddress': '10.0.0.5'})[1])
        self.assertIn('IPPort', op.resolve_port({'IPAddress': '10.0.0.5', 'IPPort': '70000'})[1])
        self.assertIn('IPAddress', op.resolve_port({'IPPort': '3001'})[1])
        self.assertIn('IPAddress', op.resolve_port({})[1])

    def test_missing_param_keys(self):
        self.assertEqual(op.missing_param_keys({'InvertInputs': 'false'}), ['IPAddress', 'IPPort'])
        self.assertEqual(op.missing_param_keys({'InvertInputs': 'false', 'IPAddress': ''}), ['IPPort'])
        self.assertEqual(op.missing_param_keys({'IPAddress': '', 'IPPort': '', 'InvertInputs': 'false'}), [])
        # empty/None config: leave alone, nothing of the user's to preserve
        self.assertEqual(op.missing_param_keys({}), [])
        self.assertEqual(op.missing_param_keys(None), [])

    def test_obsolete_param_keys_port(self):
        # empty leftover Port: safe to delete
        self.assertEqual(op.obsolete_param_keys({'Port': '', 'IPAddress': '192.168.0.70', 'IPPort': '3001'}), ['Port'])
        self.assertEqual(op.obsolete_param_keys({'Port': '   ', 'IPAddress': '', 'IPPort': ''}), ['Port'])
        # superseded by IPAddress: safe to delete even with a value
        self.assertEqual(op.obsolete_param_keys({'Port': 'socket://192.168.0.70:3001', 'IPAddress': '192.168.0.70', 'IPPort': '3001'}), ['Port'])
        # holds a value and nothing replaces it: keep it so the value is never silently lost
        self.assertEqual(op.obsolete_param_keys({'Port': 'socket://192.168.0.70:3001', 'IPAddress': '', 'IPPort': ''}), [])
        self.assertEqual(op.obsolete_param_keys({'Port': '/dev/cuaU0'}), [])

    def test_obsolete_param_keys_x10devices(self):
        base = {'InvertInputs': 'false', 'IPAddress': '192.168.0.70', 'IPPort': '3001'}
        self.assertEqual(op.obsolete_param_keys(dict(base, X10Devices='')), ['X10Devices'])
        self.assertEqual(op.obsolete_param_keys({'X10Devices': '  '}), ['X10Devices'])
        # a list has no replacement, so it is kept even when IPAddress is set
        self.assertEqual(op.obsolete_param_keys(dict(base, X10Devices='A1:Porch Light, B5')), [])
        self.assertEqual(op.obsolete_param_keys({'X10Devices': 'A1', 'IPAddress': '1.2.3.4'}), [])

    def test_obsolete_param_keys_baud(self):
        # Baud had no effect, so any value is safe to delete, with or without IPAddress
        real = {'Baud': '9600', 'InvertInputs': 'false', 'IPAddress': '192.168.0.70', 'IPPort': '3001'}
        self.assertEqual(op.obsolete_param_keys(real), ['Baud'])
        self.assertEqual(op.obsolete_param_keys({'Baud': '19200'}), ['Baud'])
        self.assertEqual(op.obsolete_param_keys({'Baud': ''}), ['Baud'])
        self.assertEqual(op.obsolete_param_keys({'Baud': 'abc', 'IPAddress': ''}), ['Baud'])

    def test_obsolete_param_keys_combined_and_nothing_to_do(self):
        self.assertEqual(op.obsolete_param_keys({'Port': '', 'X10Devices': '', 'Baud': '9600', 'IPAddress': '1.2.3.4'}), ['Port', 'X10Devices', 'Baud'])
        # a kept value does not stop the safe ones being deleted
        self.assertEqual(op.obsolete_param_keys({'Port': 'x', 'X10Devices': 'A1', 'Baud': '9600'}), ['Baud'])
        self.assertEqual(op.obsolete_param_keys({'IPAddress': '192.168.0.70', 'IPPort': '3001', 'InvertInputs': 'false'}), [])
        self.assertEqual(op.obsolete_param_keys({}), [])
        self.assertEqual(op.obsolete_param_keys(None), [])

    def test_x10_support_is_gone(self):
        for name in ('send_x10', 'get_received_x10', 'parse_x10_list', 'x10_event', 'house_code', 'unit_key', 'HOUSES', 'X10_NO_DATA'):
            self.assertFalse(hasattr(op, name), name)

    def test_parse_ir_number(self):
        self.assertEqual(op.parse_ir_number({'cmd': 'SENDIR', 'query': {'IRNUM.uom108': '12'}}), 12)
        self.assertEqual(op.parse_ir_number({'query': {'irnum': '40.0'}}), 40)
        self.assertEqual(op.parse_ir_number({'query': {'IRNUM': 0}}), 0)
        self.assertEqual(op.parse_ir_number({'query': {'IRNUM': 1023}}), 1023)

    def test_parse_ir_number_rejects_bad_input(self):
        for cmd in [{'query': {'IRNUM': 1024}}, {'query': {'IRNUM': -1}}, {'query': {'IRNUM': 'x'}},
                    {'query': {'ZONE': '3'}}, {'cmd': 'SENDIR'}, None]:
            with self.assertRaises(ValueError, msg=str(cmd)):
                op.parse_ir_number(cmd)

    def test_parse_ir_number_resident_limit(self):
        self.assertEqual(op.parse_ir_number({'query': {'IRNUM.uom108': '39'}}, op.RESIDENT_IR_MAX), 39)
        with self.assertRaises(ValueError):
            op.parse_ir_number({'query': {'IRNUM': 40}}, op.RESIDENT_IR_MAX)
        # the zone nodes keep the wider limit
        self.assertEqual(op.parse_ir_number({'query': {'IRNUM': 40}}), 40)

    def test_realtime_io_reads_256_bytes(self):
        payload = bytes(range(256))
        ser = FakeSer(bytes(6) + payload + bytes(2))
        self.assertEqual(op.get_realtime_io(ser), payload)
        self.assertEqual(ser.written[0], op.FRAME_GET_REALTIME_IO)
        self.assertIsNone(op.get_realtime_io(FakeSer(bytes(10))))


if __name__ == '__main__':
    unittest.main()
