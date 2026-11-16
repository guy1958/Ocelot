'''Controller-side glue for the Ocelot plugin. Every function takes the Controller instance.'''
import os
import threading
import time
import udi_interface
import ocelot_proto as op
from ocelot_nodes import OcelotIRZone, OcelotResidentIR, OcelotVariables, OcelotPlaceholder, io_node_class

LOGGER = udi_interface.LOGGER
TRUE_WORDS = ('1', 'true', 'yes', 'on')
LEGACY_IR_MARKER = 'legacy_ir_node_cleaned'

# The order the I/O reads are made in on each poll, and their names for the log and notices.
SOURCE_ORDER = (op.SOURCE_LATCHED, op.SOURCE_REALTIME)
SOURCE_NAMES = {op.SOURCE_LATCHED: 'Get Latched I/O', op.SOURCE_REALTIME: 'Get Real Time I/O'}

# Delete Module Nodes waits at most this long (seconds) for PG3 to confirm the node adds still queued,
# checking every ADD_WAIT_STEP seconds. PG3 confirmed adds about 0.6 s apart in the 1.16.0 log.
ADD_WAIT_TIMEOUT = 120.0
ADD_WAIT_STEP = 0.25

# Guards ctrl.pending_adds and ctrl.delete_running (touched by the add-done event thread, the command
# thread and the delete thread).
_PENDING_LOCK = threading.Lock()


def _notice(ctrl, key, text=None):
    try:
        if text is None:
            ctrl.poly.Notices.delete(key)
        else:
            ctrl.poly.Notices[key] = text
    except Exception as ex:
        LOGGER.debug('notice %s: %s' % (key, ex))


def _close(ctrl):
    with op.LOCK:
        ser = getattr(ctrl, 'ser', None)
        ctrl.ser = None
        ctrl.ser_key = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


def _remove_legacy_ir_nodes(ctrl, ir_units):
    '''Version 1.1.x made one 'u<unit>ir' node per SECU-16IR. Remove those once.'''
    pdir = getattr(ctrl, 'persist_dir', None)
    marker = os.path.join(pdir, LEGACY_IR_MARKER) if pdir else None
    if marker and os.path.exists(marker):
        return
    try:
        for unit in ir_units:
            addr = ctrl.poly.getValidAddress('u%dir' % unit)
            if ctrl.poly.getNodeNameFromDb(addr) is not None:
                LOGGER.info('Removing legacy IR module node %s (replaced by per-zone nodes)' % addr)
                ctrl.poly.delNode(addr)
        if marker:
            with open(marker, 'w') as fh:
                fh.write('done\n')
    except Exception as ex:
        LOGGER.warning('Legacy IR node cleanup failed (will retry next start): %s' % ex)


def _sync_params(ctrl, params):
    '''Keep the saved config in line with the current settings: add new empty ones, delete removed ones.

    PG3's Custom._save() sends the WHOLE customparams dict, so the current values are loaded into the
    store first; otherwise saving would wipe every other setting. Removed settings are only deleted
    when op.obsolete_param_keys() says it is safe.
    '''
    missing = op.missing_param_keys(params)
    obsolete = op.obsolete_param_keys(params)
    if not missing and not obsolete:
        return
    try:
        store = udi_interface.Custom(ctrl.poly, 'customparams')
        store.load(params)
        for key in missing:
            store[key] = ''
        for key in obsolete:
            store.delete(key)
        if missing:
            LOGGER.info('Added new empty settings to the configuration page: %s' % ', '.join(missing))
        if obsolete:
            LOGGER.info('Removed obsolete settings from the configuration page: %s' % ', '.join(obsolete))
    except Exception as ex:
        LOGGER.warning('Could not update the saved settings (add %s, remove %s): %s' % (missing, obsolete, ex))


def set_params(ctrl, params):
    ctrl.ocelot_params = {str(k): v for k, v in (params or {}).items()}
    _sync_params(ctrl, ctrl.ocelot_params)
    if getattr(ctrl, 'ocelot_started', False):
        discover(ctrl)


def _pending(ctrl):
    '''The set of module node addresses whose add PG3 has not confirmed yet (create it if missing).

    Call with _PENDING_LOCK held.
    '''
    pending = getattr(ctrl, 'pending_adds', None)
    if pending is None:
        pending = ctrl.pending_adds = set()
    return pending


def _add_node(ctrl, node):
    '''poly.addNode() for a module node, remembering the add as unconfirmed until PG3's add-node-done event.

    PG3 works through its queue of node adds slowly (about 0.6 s per node), so an add can still be
    pending long after this call returns. Delete Module Nodes waits for these (see delete_modules()).
    The address is recorded before the add is sent so a fast confirmation cannot be missed.
    '''
    with _PENDING_LOCK:
        _pending(ctrl).add(node.address)
    try:
        ctrl.poly.addNode(node)
    except Exception:
        with _PENDING_LOCK:
            _pending(ctrl).discard(node.address)
        raise


def add_done(ctrl, data):
    '''Handle PG3's add-node-done event: that node's add is confirmed. Anything unexpected is ignored.'''
    address = data.get('address') if isinstance(data, dict) else None
    if address is None:
        return
    with _PENDING_LOCK:
        _pending(ctrl).discard(address)


def _subscribe_add_done(ctrl):
    '''Listen for add-node-done events (once). If that fails, tracking is turned off so nothing waits for them.'''
    if getattr(ctrl, 'add_done_listener', None) is not None:
        return

    def listener(data, _ctrl=ctrl):
        add_done(_ctrl, data)

    try:
        ctrl.poly.subscribe(ctrl.poly.ADDNODEDONE, listener)
    except Exception as ex:
        ctrl.add_tracking = False
        LOGGER.warning('Could not listen for node-added confirmations (%s); Delete Module Nodes will not wait for pending adds' % ex)
        return
    ctrl.add_done_listener = listener
    ctrl.add_tracking = True


def start(ctrl):
    ctrl.ser = None
    ctrl.ser_key = None
    ctrl.io_nodes = {}
    ctrl.ir_nodes = {}
    ctrl.placeholder_nodes = {}
    ctrl.resident_ir = None
    ctrl.var_node = None
    ctrl.io_fail = 0
    ctrl.ocelot_ready = False
    ctrl.ocelot_started = True
    ctrl.pending_adds = set()
    ctrl.delete_running = False
    _subscribe_add_done(ctrl)
    discover(ctrl)


def stop(ctrl):
    ctrl.ocelot_ready = False
    ctrl.ocelot_started = False
    _close(ctrl)


def _sync_placeholders(ctrl, unsupported):
    '''Make one placeholder node per unsupported module ({unit: type code}); keep the set current.

    A placeholder for a module that has gone, or that now reports another type, is deleted; one that
    already exists is left alone, so repeated discovery never duplicates it. Placeholders have no
    commands and are never polled.
    '''
    held = getattr(ctrl, 'placeholder_nodes', None)
    if held is None:
        held = ctrl.placeholder_nodes = {}
    wanted = {}
    for unit, utype in sorted(unsupported.items()):
        wanted[ctrl.poly.getValidAddress(op.placeholder_address(unit, utype))] = (unit, utype)
    for addr in [a for a in held if a not in wanted]:
        LOGGER.info('Removing placeholder node %s (that module is gone or reports another type)' % addr)
        try:
            ctrl.poly.delNode(addr)
        except Exception as ex:
            LOGGER.warning('Could not remove placeholder node %s: %s' % (addr, ex))
        del held[addr]
    for addr, (unit, utype) in wanted.items():
        if addr in held:
            continue
        name = ctrl.poly.getValidName(op.placeholder_name(unit, utype))
        node = OcelotPlaceholder(ctrl.poly, ctrl.address, addr, name, unit, utype)
        _add_node(ctrl, node)
        held[addr] = node
        LOGGER.info('Created placeholder node "%s" for the unsupported module type %d at unit %d' % (name, utype, unit))


def discover(ctrl):
    params = getattr(ctrl, 'ocelot_params', None) or {}
    ctrl.ocelot_ready = False
    port, err = op.resolve_port(params)
    if err:
        _notice(ctrl, 'config', err)
        return
    _notice(ctrl, 'config')
    invert = str(params.get('InvertInputs', '') or '').strip().lower() in TRUE_WORDS
    if str(params.get('X10Devices', '') or '').strip():
        _notice(ctrl, 'x10', 'X-10 support was removed in version 1.7.0, so the X10Devices setting is ignored. Clear or delete it to dismiss this notice.')
    else:
        _notice(ctrl, 'x10')

    if ctrl.ser is not None and ctrl.ser_key != port:
        _close(ctrl)
    if ctrl.ser is None:
        LOGGER.info('Connecting to %s' % port)
        try:
            ctrl.ser = op.open_port(port)
            ctrl.ser_key = port
        except Exception as ex:
            LOGGER.error('Cannot open %s: %s' % (port, ex))
            _notice(ctrl, 'serial', 'Cannot open %s: %s' % (port, ex))
            return

    data = op.get_unit_types(ctrl.ser)
    if data is None:
        LOGGER.error('No answer to Get Unit Type on %s' % port)
        _notice(ctrl, 'serial', 'Opened %s but the Ocelot did not answer. Check the cable, the IPAddress/IPPort settings, and the serial settings on the adapter.' % port)
        return

    types = op.parse_unit_types(data)
    supported, unsupported, empty = op.classify_units(types)
    LOGGER.info('Ocelot units found (unit: type code): %s' % supported)
    if empty:
        LOGGER.debug('%d unit slots report the empty-slot marker (254); ignored' % len(empty))
    if unsupported:
        LOGGER.info('Unsupported module types found (unit: type code), placeholder nodes are made for them: %s' % unsupported)
    _notice(ctrl, 'units')
    _sync_placeholders(ctrl, unsupported)
    ir_units = [u for u, t in supported.items() if t == op.TYPE_SECU16IR]
    if ir_units:
        _remove_legacy_ir_nodes(ctrl, ir_units)
    for unit, utype in supported.items():
        if utype == op.TYPE_SECU16IR:
            for zone in range(op.IR_ZONES):
                addr = ctrl.poly.getValidAddress('u%dz%d' % (unit, zone))
                if addr in ctrl.ir_nodes:
                    continue
                name = ctrl.poly.getValidName('Mod %d IR Zone %d' % (unit, zone))
                node = OcelotIRZone(ctrl.poly, ctrl.address, addr, name, ctrl, unit, zone)
                _add_node(ctrl, node)
                ctrl.ir_nodes[addr] = node
            continue
        source = op.io_source_for_unit(utype)
        for kind, idx, byte, bit in op.points_for_unit(utype):
            tag = 'r' if kind == 'relay' else 'i'
            addr = ctrl.poly.getValidAddress('u%d%s%d' % (unit, tag, idx))
            node = ctrl.io_nodes.get(addr)
            if node is not None:
                if kind == 'input':
                    node.invert = invert
                continue
            name = ctrl.poly.getValidName('Mod %d %s %d' % (unit, kind.capitalize(), idx))
            # the node class sets the node type (profile nodedef) for this module kind, e.g. SECU16I Input
            node_class = io_node_class(utype, kind)
            if kind == 'relay':
                node = node_class(ctrl.poly, ctrl.address, addr, name, ctrl, unit, idx, byte, bit, source)
            else:
                node = node_class(ctrl.poly, ctrl.address, addr, name, unit, idx, byte, bit, invert, source)
            _add_node(ctrl, node)
            ctrl.io_nodes[addr] = node

    if getattr(ctrl, 'resident_ir', None) is None:
        addr = ctrl.poly.getValidAddress('residentir')
        node = OcelotResidentIR(ctrl.poly, ctrl.address, addr, ctrl.poly.getValidName('Ocelot Resident IR'), ctrl)
        ctrl.poly.addNode(node)
        ctrl.resident_ir = node

    if getattr(ctrl, 'var_node', None) is None:
        addr = ctrl.poly.getValidAddress('cpuxavars')
        node = OcelotVariables(ctrl.poly, ctrl.address, addr, ctrl.poly.getValidName('Ocelot Variables'), ctrl)
        ctrl.poly.addNode(node)
        ctrl.var_node = node

    ctrl.io_fail = 0
    ctrl.ocelot_ready = True
    _notice(ctrl, 'serial')
    poll(ctrl)
    _refresh_variables(ctrl)


def _refresh_variables(ctrl, quiet=False):
    '''Read the variable table (Discover, Query, and every short poll via short_poll()).

    quiet=True logs a successful read at debug level (used by the short poll).
    '''
    node = getattr(ctrl, 'var_node', None)
    if node is None or getattr(ctrl, 'ser', None) is None:
        return
    try:
        node.refresh(quiet=quiet)
    except Exception as ex:
        LOGGER.error('Variable refresh failed: %s' % ex)


def _read_source(ser, source):
    '''One I/O read: Get Latched I/O for the latched source, otherwise Get Real Time I/O.'''
    if source == op.SOURCE_LATCHED:
        return op.get_latched_io(ser)
    return op.get_realtime_io(ser)


def _node_source(node):
    return getattr(node, 'source', op.SOURCE_REALTIME)


def poll(ctrl, sources=None, skip=None):
    '''Read the I/O and update the relay and input nodes.

    By default (sources=None) only the reads that the installed nodes need are made: Get Latched I/O
    when there are SECU-16 or SECU-16I nodes, then Get Real Time I/O when there are RLY08-XA nodes.
    With no I/O nodes at all one Get Real Time I/O read is still made, as the check that the Ocelot
    answers. Each node is updated from the read that supplies it. If any read gets no answer the
    poll counts as failed (io_fail), but the nodes of a read that did answer are still updated.

    sources limits the poll to those sources (a tuple of op.SOURCE_* values), and only those that
    installed nodes actually use are read: OcelotRelay passes (op.SOURCE_LATCHED,) after a relay
    command, so no real-time read is made, and nothing at all is read when there are no latched nodes.

    skip is a tuple of nodes whose status is left as it is (the read is still made and still counts):
    OcelotRelay passes itself after an acknowledged command, because a latched relay bit read right
    after the command can still carry the old state and would undo the status just sent to IoX.
    '''
    if not getattr(ctrl, 'ocelot_ready', False) or getattr(ctrl, 'ser', None) is None:
        return
    nodes = list(ctrl.io_nodes.values())
    present = {_node_source(n) for n in nodes}
    if sources is None:
        chosen = [s for s in SOURCE_ORDER if s in present] or [op.SOURCE_REALTIME]
    else:
        chosen = [s for s in SOURCE_ORDER if s in present and s in sources]
        if not chosen:
            return
    skipped = {id(n) for n in (skip or ())}
    failed = []
    for source in chosen:
        try:
            data = _read_source(ctrl.ser, source)
        except Exception as ex:
            LOGGER.error('I/O poll (%s) failed: %s' % (SOURCE_NAMES[source], ex))
            data = None
        if data is None:
            failed.append(SOURCE_NAMES[source])
            continue
        for node in nodes:
            if _node_source(node) == source and id(node) not in skipped:
                node.update_from(data)
    if failed:
        if ctrl.io_fail == 0:
            LOGGER.warning('No valid answer to: %s' % ', '.join(failed))
        ctrl.io_fail += 1
        if ctrl.io_fail == 3:
            _notice(ctrl, 'serial', 'The Ocelot has stopped answering (no valid answer to: %s). Will keep retrying.' % ', '.join(failed))
        return
    if ctrl.io_fail >= 3:
        _notice(ctrl, 'serial')
    ctrl.io_fail = 0


def short_poll(ctrl):
    '''Every short poll: read the I/O (latched and/or real-time), then the 128 program variables.

    The variable read is skipped when any I/O read in this same cycle got no answer (the link is
    probably down; another read would only add another timeout) or the plugin is not ready.
    poll() itself is left as it was because discover() and query() call it and already read the
    variables themselves.
    '''
    if not getattr(ctrl, 'ocelot_ready', False) or getattr(ctrl, 'ser', None) is None:
        return
    poll(ctrl)
    if getattr(ctrl, 'io_fail', 0) != 0:
        return
    _refresh_variables(ctrl, quiet=True)


def long_poll(ctrl):
    if not getattr(ctrl, 'ocelot_started', False):
        return
    if (not getattr(ctrl, 'ocelot_ready', False)) or getattr(ctrl, 'io_fail', 0) >= 3:
        _close(ctrl)
        discover(ctrl)


def rescan(ctrl):
    ser = getattr(ctrl, 'ser', None)
    if ser is None:
        LOGGER.error('Rescan requested but the serial port is not open')
        return
    ok = op.rescan(ser)
    LOGGER.info('Rescan %s' % ('acknowledged' if ok else 'NOT acknowledged'))
    time.sleep(2)
    discover(ctrl)


def _wait_for_pending_adds(ctrl, timeout=None, step=None):
    '''Wait until PG3 has confirmed every module node add. Returns how many were still unconfirmed (0 = all done).

    Gives up after timeout seconds (default ADD_WAIT_TIMEOUT), checking every step seconds (default
    ADD_WAIT_STEP). Returns 0 at once when add tracking is off (the confirmation event could not be
    subscribed to), since nothing would ever clear the pending set.
    '''
    timeout = ADD_WAIT_TIMEOUT if timeout is None else timeout
    step = ADD_WAIT_STEP if step is None else step
    if getattr(ctrl, 'add_tracking', True) is False:
        return 0
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        with _PENDING_LOCK:
            left = len(_pending(ctrl))
        if left == 0:
            return 0
        if time.monotonic() >= deadline:
            return left
        if not announced:
            LOGGER.info('Delete Module Nodes: waiting for PG3 to finish adding %d nodes before deleting' % left)
            announced = True
        time.sleep(step)


def _delete_module_nodes(ctrl):
    '''Delete every expansion-module node this run knows about: relays, inputs, SECU-16IR zones, placeholders.

    The Controller, the Ocelot Resident IR node and the Ocelot Variables node are kept: they belong to
    the Ocelot itself, not to an expansion module. Nothing is sent to the Ocelot.

    The registries are emptied first (in place, so every reference to them stays valid), so a poll running
    at the same moment no longer sees the nodes about to go; then each node is deleted. One node that
    cannot be deleted is logged and does not stop the others. Discover, Rescan Modules, a connection
    setting change and a plugin restart create the module nodes again, because they are found on the
    Ocelot. Only nodes this run created or re-discovered are known: a node left over from an earlier run
    (for example a placeholder whose module has gone) is not in the registries and stays.
    '''
    addresses = []
    for registry_name in ('io_nodes', 'ir_nodes', 'placeholder_nodes'):
        registry = getattr(ctrl, registry_name, None)
        if registry:
            addresses.extend(registry.keys())
            registry.clear()
    if not addresses:
        LOGGER.info('Delete Module Nodes: there are no expansion module nodes to delete')
        return
    with _PENDING_LOCK:
        _pending(ctrl).difference_update(addresses)
    removed, failed = 0, 0
    for addr in addresses:
        try:
            ctrl.poly.delNode(addr)
            removed += 1
        except Exception as ex:
            failed += 1
            LOGGER.warning('Delete Module Nodes: could not delete node %s: %s' % (addr, ex))
    LOGGER.info('Delete Module Nodes: deleted %d module nodes%s (the controller, Ocelot Resident IR and Ocelot Variables are kept)'
                % (removed, ', %d could not be deleted' % failed if failed else ''))


def _delete_worker(ctrl, wait=None):
    '''Body of the Delete Module Nodes thread: wait for PG3's pending adds, then delete (see delete_modules()).'''
    try:
        left = _wait_for_pending_adds(ctrl, wait)
        if left:
            LOGGER.warning('Delete Module Nodes: PG3 had still not confirmed %d node adds after waiting; deleting anyway. '
                           'Any of those nodes that PG3 adds afterwards will stay: press Discover, wait, then Delete Module Nodes again.' % left)
        _delete_module_nodes(ctrl)
    except Exception as ex:
        LOGGER.error('Delete Module Nodes failed: %s' % ex)
    finally:
        with _PENDING_LOCK:
            ctrl.delete_running = False


def delete_modules(ctrl, wait=None):
    '''The Delete Module Nodes command: delete the expansion-module nodes in a background thread.

    PG3 confirms node adds slowly (about 0.6 s each), and removing a node whose add is still queued does
    not stop that add: PG3 creates it afterwards (seen in the 1.16.0 log, 17 nodes re-created after the
    delete). So the thread first waits for PG3 to confirm the pending adds (up to wait seconds, default
    ADD_WAIT_TIMEOUT), then deletes. It is a thread so the command handler is not blocked: the
    confirmations are processed by the same handler. A second press while one is running is ignored.

    Returns the thread that was started, or None when one was already running.
    '''
    with _PENDING_LOCK:
        if getattr(ctrl, 'delete_running', False):
            already = True
        else:
            already = False
            ctrl.delete_running = True
    if already:
        LOGGER.info('Delete Module Nodes: already in progress, this request is ignored')
        return None
    thread = threading.Thread(target=_delete_worker, args=(ctrl, wait), name='ocelot-delete-modules', daemon=True)
    thread.start()
    return thread


def query(ctrl):
    poll(ctrl)
    _refresh_variables(ctrl)
    ctrl.reportDrivers()
    nodes = (list(getattr(ctrl, 'io_nodes', {}).values())
             + list(getattr(ctrl, 'ir_nodes', {}).values())
             + list(getattr(ctrl, 'placeholder_nodes', {}).values()))
    for extra in (getattr(ctrl, 'resident_ir', None), getattr(ctrl, 'var_node', None)):
        if extra is not None:
            nodes.append(extra)
    for n in nodes:
        n.reportDrivers()
