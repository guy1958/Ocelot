# Ocelot

# Ocelot (Adicon / Applied Digital)

An IoX plugin for the Applied Digital **Ocelot** home-automation controller (the second-generation CPU-XA), talking its serial protocol through a serial-to-Ethernet adapter (raw TCP).

## What you get

* **Controller node**: connection status (managed by PG3), plus *Query*, *Rescan Modules* and *Delete Module Nodes* commands. There is no separate *Discover* button since 1.18.0; *Rescan Modules* does the discovery (see "Changed in 1.18.0").
* **Relay nodes** (On/Off) for every relay on SECU-16 and RLY08-XA expansion modules (node types *SECU16 Relay* and *RLY08XA Relay*). When the Ocelot acknowledges an On/Off command the new state is sent to IoX immediately and stays shown (see "Changed in 1.15.0"); the plugin then re-reads the latched inputs and relays of the SECU-16 and SECU-16I modules (see "Changed in 1.13.0").
* **Input nodes** (On/Off) for every digital input bit on SECU-16 and SECU-16I modules (node types *SECU16 Input* and *SECU16I Input*). They also send DON/DOF on change (named *On* and *Off* in the Program editor) so Programs can trigger on them.
* **IR zone nodes**: 16 per SECU-16IR module (node type *SECU16IR Zone*), each with a **Send IR** command that takes an *IR Number* (0-1023). See "IR output" below.
* **Resident IR node**: `Ocelot Resident IR`, with a **Send Resident IR** command that takes an *IR Number* (0-39) and makes the Ocelot itself transmit it. See "IR output" below.
* **Variables node**: `Ocelot Variables`, with a **Write Variable** command that writes a 16-bit value into one of the Ocelot's program variables (0-127), and **Get Variables** / **Read Variable** commands that read them back. The variables are also re-read on every short poll and right after every write. Since 1.19.0 each of the 128 variables also has its own property (**Variable 0** to **Variable 127**), so a Program can test any variable directly, and since 1.20.0 each of them has an edit command with the same id. In eisyUI the tiles at the top of the node page are display-only; the edit inputs are in the list of commands at the bottom of the page (see "Changed in 1.20.2"). See "Program variables" below.
* **Placeholder nodes** for expansion modules of a type this plugin does not support, named `Mod <unit> Type <type number>` (see "Unsupported modules" below). They have no commands.

Nodes are named `Mod <unit> Relay <n>` / `Mod <unit> Input <n>` / `Mod <unit> IR Zone <n>`, using the 0-based point numbering of C-Max's "Module/Point" convention. You can rename them in the admin console (for example after the room or device each IR zone feeds).

## Node types (the Type column)

Since 1.17.0 each kind of module point has its own node type, so the Type column in the admin console tells you which module a node belongs to:

| Module (unit type code) | Inputs | Relays | IR zones |
|---|---|---|---|
| SECU-16 (11) | SECU16 Input | SECU16 Relay | |
| SECU-16I (12) | SECU16I Input | | |
| RLY08-XA (13) | | RLY08XA Relay | |
| SECU-16IR (6) | | | SECU16IR Zone |
| any other code | | | placeholder: Ocelot Unsupported Module |

The Controller, Ocelot Resident IR and Ocelot Variables keep their own types.

## Connecting to the Ocelot

Set two settings, both required:

* **IPAddress**: the IPv4 address or host name of the serial-to-Ethernet adapter (for example `192.168.0.70`; no `socket://` prefix, no `:port`).
* **IPPort**: the adapter's TCP port for the Ocelot's serial port (1-65535, for example `3001`).

The plugin joins them as `socket://IPAddress:IPPort`. Invalid or missing values (for example `192.168.0.700`, an empty IPPort, or a port outside 1-65535) show a notice on the configuration page and nothing is opened. Changing either setting makes the plugin reconnect and re-scan.

The speed and format of the serial link are set on the adapter, not in this plugin, and must match the Ocelot's.

Connecting directly to a serial device on the eisy (a path such as `/dev/cuaU0`) is not supported.

## Unsupported modules

The plugin asks the Ocelot for the type code of every expansion module (Get Unit Type) at startup, after **Rescan Modules**, when a connection setting changes, and on the once-a-minute retry while the Ocelot is not answering. Types 6 (SECU-16IR), 11 (SECU-16), 12 (SECU-16I) and 13 (RLY08-XA) get their real nodes. The reply value 254 means an empty slot and is ignored. **Any other type code gets a placeholder node** (added in 1.14.0):

* The node is named `Mod <unit> Type <type>`, for example `Mod 5 Type 20` for the module at unit 5 that reports type 20. Its address is `u<unit>t<type>` (`u5t20`).
* Its only property, **Module Type**, shows the type number the Ocelot reported.
* It has **no commands**, is **never polled**, and does nothing else. It only marks that the module exists, until real support for that type is added. It also does not read or control anything on that module.
* Discovering again does not create a second copy. If that module later reports a different type, or is no longer found, or becomes a supported type, its placeholder is deleted (and a new placeholder or real nodes are created if that applies). If the Ocelot gives no answer to Get Unit Type, nothing is added or removed.
* The notice banner "Ignored expansion modules of an unsupported type", shown by versions up to 1.13.0, no longer exists because these modules are no longer ignored. The log records the units and type codes found.
* A placeholder is only removed while the plugin is running and notices the change. One that was made in an earlier run and whose module is gone is not known to the plugin after a restart and stays until you delete it yourself.
* The new node type is part of the node profile, so it appears in the admin console once the plugin has restarted and re-sent its profile.

## Changed in 1.20.2

* **The edit commands have `init` again.** Each of the 128 `VAR_<n>` commands (the ones added in 1.20.0) has one unnamed value parameter whose `init` is the property's own id (`init="VAR_17"` for Variable 17). 1.20.1 had removed it. From reading eisyUI's code, `init` is what pre-fills the command's input with the property's current value; whether anything else depends on it was not checked.
* **Where to edit a variable in eisyUI (reported by the installer).** On the `Ocelot Variables` node page, the **Variable 0** to **Variable 127** tiles near the top only display the current values. The edit inputs are in the list of the node's commands at the very bottom of the page. Reading eisyUI's code agrees: its property tile has no input, and a command with a value parameter gets its own input. How the admin console and UD Mobile present these commands was not checked.
* **An earlier version of this note was wrong.** It said the Variable fields were "not editable" at 1.20.1 and that restoring `init` was the likely fix. The 1.20.1 report came from looking at the tiles near the top; the installer found the command list only afterwards, with 1.20.2 loaded. So it is **not known** whether the edit inputs already existed at 1.20.1 (without `init`), and `init` has **not** been shown to fix anything. The cause of the 1.20.0 profile rejection is also still unknown (see 1.20.1).
* **To keep the profile small the edit commands also lose `native`.** IoX's own stored copy of other commands (for example Write Variable) carries no `native` attribute, so it looks unused there; what it does for these commands was not checked, and the plugin assumes the default (not a standard command). The profile is about 28.4 KB compact; the version IoX accepted at 1.20.1 was 28.5 KB. `optional` stays removed.
* **Nothing else changes.** The code is the same as 1.20.0 and 1.20.1; Write Variable, Get Variables and Read Variable keep their full parameter definitions.
* **Checked on the installer's system:** the 1.20.2 profile was accepted (update response `success`), and IoX's stored copy holds all 128 `VAR_<n>` commands, each with `init` set to its own id. The installer saw the edit inputs in the command list. **Not checked:** that a value entered there reaches the Ocelot. After an edit, **Last Write Result** should show "Acknowledged" and the variable's tile should show the value the Ocelot reports. Use a scratch variable for a test: variable 62 changes by itself (see "Program variables").
* Covered by the hardware-free tests (`tests/test_ocelot_varedit.py`).

## Changed in 1.20.1

* **The node profile is smaller.** The 128 edit commands added in 1.20.0 (one per variable) no longer carry the parameter's *init* and *optional* fields. The profile goes from about 32.7 KB to about 28.5 KB (compact JSON). (`init` came back in 1.20.2, see above.)
* **Why:** after 1.20.0 the profile update the plugin makes at every start was rejected twice by the platform (`write ENOTCONN`, then `write EPIPE`), while the smaller 1.19.0 profile (about 13 KB) had been accepted. At 1.20.1 the update was accepted (`success`), which fits the size explanation, but a single success does not prove it: the log never said why the earlier writes failed.
* **What you lose:** a parameter without *optional* is treated by this plugin as required: a command without a value is refused (logged, **Last Write Result** shows "Not Acknowledged"). What IoX does with a missing *optional* field in its own dialogs was not checked.
* **Result at 1.20.1:** the installer reported the Variable fields as not editable, but that report was about the tiles near the top of the node page, which are display-only. Whether the edit inputs in the command list existed at 1.20.1 was never checked (see 1.20.2).
* **Nothing else changes.** The code is the same as 1.20.0; **Write Variable**, **Get Variables** and **Read Variable** keep their full parameter definitions.

## Changed in 1.20.0

* **Every variable property has an edit command.** Each of **Variable 0** to **Variable 127** (ids `VAR_0` to `VAR_127`) has its own command with the same id, taking one value (0-65535). It follows the usual IoX pattern for an editable property: a command with the same id as the property and a single unnamed value parameter. A Program can use it too (Then: *Variable 17*, set the value). In eisyUI the edit inputs are in the list of the node's commands at the bottom of the node page, not in the property tiles at the top (see 1.20.2). How the admin console and UD Mobile present them was not checked.
* **It does exactly what Write Variable does.** The value is written with the protocol's *Write CPUXA Variable Data* (command 41), then all variables are read again straight away. **Last Write Result**, **Last Variable** and **Last Value Written** are updated as for Write Variable.
* **The property shows what the Ocelot holds, not what you typed.** After the write the plugin reads the variables back and publishes the result, so if the Ocelot does not acknowledge the write and the value does not change, the property keeps its old value and **Last Write Result** shows "Not Acknowledged". An unacknowledged write may still have taken effect; the read-back shows which it was.
* **A value that is not a whole number from 0 to 65535 is refused** (logged, **Last Write Result** shows "Not Acknowledged", nothing is sent to the Ocelot). The same happens when the serial port is not open.
* **Write Variable is unchanged** (variable number and value as two parameters), and so are **Get Variables**, **Read Variable** and the read-only use of the properties in Program conditions.
* **128 more commands are part of the node profile**, so they appear once the plugin has restarted and re-sent its profile. On the installer's system the profile update was rejected at both restarts after 1.20.0 (see 1.20.1).
* Covered by the hardware-free tests (`tests/test_ocelot_varedit.py`).

## Changed in 1.19.0

* **Every program variable now has its own property, so a Program can read any of them.** The `Ocelot Variables` node gets 128 new properties, **Variable 0** to **Variable 127** (ids `VAR_0` to `VAR_127`), each an unsigned 16-bit value (0-65535). A Program condition can now test one directly, for example *If 'Ocelot Variables' Variable 17 is greater than 5*. Before, only the one variable chosen with **Read Variable** was visible, in **Read Value**, which made reading a specific variable from a Program a two-step, timing-dependent sequence.
* **Variables 60 to 63 keep their labels in the property names**: "Variable 60 Last received IR", "Variable 61 Leopard Beep Counter", "Variable 62 Beep Duration" and "Variable 63 Leopard Screen Number" (same wording as in the variable list; see 1.9.2).
* **The properties are filled from the reads the plugin already makes**: the table is read on every short poll, right after every Write Variable, and on Get Variables, Read Variable, Query and discovery. No extra request is sent to the Ocelot. After a successful read every variable that changed is published; a read that gets no valid answer leaves them as they were (only **Last Read Result** changes).
* **Only changed values are sent.** The plugin remembers what it last published and sends a variable only when its value differs, so the poll every 5 seconds does not send 128 updates each time. The first read after a plugin start sends all 128.
* **In 1.19.0 they were read-only.** Writing was done only with **Write Variable** (variable number and value); since 1.20.0 each property also has an edit command (see above).
* **Nothing else changes.** The six existing properties (**Last Write Result**, **Last Variable**, **Last Value Written**, **Last Read Result**, **Read Variable**, **Read Value**) and the **Write Variable**, **Get Variables** and **Read Variable** commands are as before, so existing Programs keep working.
* **The new properties are part of the node profile**, so they appear in the admin console and Programs once the plugin has restarted and re-sent its profile. After the restart the installer confirmed that all the variables are shown in the `Ocelot Variables` node.
* Covered by the hardware-free tests (`tests/test_ocelot_varprops.py`).

## Changed in 1.18.0

* **The Discover button is gone from the Ocelot Controller node.** The *Discover* command was removed from the controller's commands, so it no longer appears in the admin console or as a choice in a Program (Then: ...). A Program that used it will need another command.
* **Rescan Modules replaces it.** It asks the Ocelot to re-detect its modules (protocol command 32), waits 2 seconds, then runs the same discovery the Discover button ran: it creates any missing module nodes and placeholders and reads the I/O and variables once. Use it after adding, removing or re-addressing an expansion module. If the serial connection is not open it logs an error and does nothing; in that case the plugin reconnects by itself within a minute (or restart it).
* **Discovery itself is unchanged and still runs on its own** at plugin startup, when IPAddress or IPPort changes, from Rescan Modules, and on the once-a-minute retry while the Ocelot is not answering. Only the button was removed.
* **After Delete Module Nodes, use Rescan Modules** (or restart the plugin) to bring the nodes back; before 1.18.0 this was the Discover button.
* The *Discover* entry that PG3 itself may show on the plugin's page (the plugin still declares that it supports discovery) was not changed.
* Covered by the hardware-free tests; not yet checked on the installer's system.

## Changed in 1.17.0

* **Per-module node types.** The Type column used to say "Ocelot Input" or "Ocelot Relay" for every module. Now it names the module kind: *SECU16 Input*, *SECU16 Relay*, *SECU16I Input*, *RLY08XA Relay* and *SECU16IR Zone* (see "Node types" above). The old generic types `relay`, `input` and `irzone` no longer exist in the profile.
* **Nothing else changes.** Commands (On/Off, Send IR), properties and their labels, DON/DOF events from inputs, node addresses (`u2i0`) and node names (`Mod 2 Input 0`) are as before. The polling, the latched and real-time reads and the delete command are untouched.
* **Existing nodes keep their old type until they are deleted.** PG3 is only asked to add a node; this plugin could not check what PG3 does when a node that already exists is added again with a different type, so the safe route is to recreate them. After upgrading and restarting: press **Delete Module Nodes** (it waits for PG3 to finish adding nodes, see 1.16.1), then press **Discover** (since 1.18.0: **Rescan Modules**). The nodes come back with the new types.
* **Programs and scenes** that use a module node lose that reference when the node is deleted (as with any delete); check them afterwards. Program conditions that used an input's DON/DOF still work once the node exists again.
* **Resident IR, Variables and the Controller are not touched** and do not need recreating.
* Checked on the installer's system: after the restart PG3 reported 8 SECU16 Input, 8 SECU16 Relay and 16 SECU16I Input nodes, and the installer confirmed the Type column looks right. Covered by hardware-free tests (`tests/test_ocelot_nodetypes.py`).

## Changed in 1.16.1

* **Fixed: Delete Module Nodes could leave nodes behind.** In 1.16.0, pressing it soon after the plugin started (or after Discover) deleted the nodes while PG3 was still working through its queue of node additions. PG3 confirms those additions slowly (about 0.6 seconds per node, so about 25 seconds for 40 nodes). A removal does not cancel an addition still waiting in that queue, so PG3 created those nodes anyway afterwards; the plugin had already forgotten them, so a second press found nothing to delete. In the 1.16.0 log, 17 module nodes (Mod 2 Input 15, Mod 4 Input 0-7 and Mod 4 Relay 0-7) were created after the removal had been acknowledged. That explanation rests on the timestamps in that log (adds confirmed after the removals); IoX's own node list was not examined.
* **What it does now:** the plugin remembers every module node it has asked PG3 to add until PG3 confirms it (the add-node-done event). **Delete Module Nodes** then runs in a background thread: it first waits until all of those are confirmed, and only then deletes. The log says "waiting for PG3 to finish adding N nodes" when it has to wait.
* **The wait is at most 2 minutes.** If PG3 still has not confirmed some adds by then, the plugin logs a warning and deletes anyway. A node PG3 adds after that stays: press **Rescan Modules** (before 1.18.0: Discover), wait for the nodes to appear, then press **Delete Module Nodes** again.
* **A second press while a delete is running is ignored** (it is logged). After it finishes, the command can be used again.
* **If the plugin cannot listen for PG3's confirmations** (a warning is logged at startup), it does not wait, and behaves like 1.16.0.
* **Nodes left over from the 1.16.0 problem:** they exist in IoX but were not tracked. Restarting the plugin makes discovery add every module node again, which tracks them, so the next **Delete Module Nodes** removes them too.
* **Resident IR and Variables** are not module nodes: they are still never deleted, and the command does not wait for them.
* Checked on the installer's system with 1.16.1: two presses of Delete Module Nodes each deleted all 34 module nodes, and Discover created them again (from the log; IoX's own node list was not examined).

## Changed in 1.16.0

* **New controller command: Delete Module Nodes.** It is a button on the root *Ocelot Controller* node in the admin console, and can also be used from a Program (Then: *Delete Module Nodes*). It deletes every expansion module node the running plugin knows about: all relay nodes, all input nodes, all SECU-16IR zone nodes and all placeholder nodes.
* **What is kept:** the *Ocelot Controller* itself, **Ocelot Resident IR** and **Ocelot Variables**. Those belong to the Ocelot itself, not to an expansion module, so this command never deletes them.
* **Nothing is sent to the Ocelot.** Only nodes in IoX are deleted; the modules and their relays are not touched.
* **The nodes come back.** The module nodes are found on the Ocelot, so discovery (**Rescan Modules**, a change to IPAddress or IPPort, and a plugin restart; in 1.16.0 also the Discover button) creates them again. The command clears them; it does not stop them being discovered.
* **Programs and scenes** that use a deleted node lose that reference. There is no confirmation step when the button is pressed. Nodes that are created again by discovery get the same addresses and names as before, but any Program or scene entry that pointed at a deleted node has to be checked.
* **Only nodes this run knows about are deleted.** A node left over from an earlier run (for example a placeholder whose module has since gone, see "Unsupported modules") is not tracked after a restart, so it stays and has to be deleted by hand.
* **A node that cannot be deleted is logged and skipped;** the others are still deleted. The log shows how many module nodes were deleted (and how many could not be).
* **While the module nodes are cleared, each short poll only makes its link check** (one Get Real Time I/O read, to confirm the Ocelot still answers), and the variables keep being read as before.
* Version 1.16.0 had a timing problem when pressed soon after startup or Discover; it is fixed in 1.16.1 (see above).

## Changed in 1.15.0

* **A relay command is reflected in IoX immediately and stays.** When the Ocelot acknowledges an On or Off command, the plugin sends the new state to IoX at once. It is sent every time, even if the plugin already believed the relay was in that state (before, an unchanged value was not sent at all).
* **The read that follows no longer undoes it.** After every relay command the plugin still reads the latched I/O (see 1.13.0), and that still refreshes the inputs and the other relays of the SECU-16 and SECU-16I modules and clears the latches. But it now leaves the relay you just commanded alone.
* **Why:** in the 1.14.0 log, SECU-16 relay 7 of unit 2 was sent Off at 13:55:06.305. Its status showed Off 0.2 s later, then went back to **On** 0.3 s after that, because the latched read right after the command still carried the old On; the next regular poll corrected it to Off at 13:55:09. The same happened after On commands, where the read right after showed Off. Relay 5 of unit 1 did the same, and the RLY08-XA relay (unit 3, relay 3) did not, because the latched read does not touch it. The explanation (a latched relay bit and the Ocelot's own update lagging the command) is an inference from that log, not documented behaviour.
* **The next regular poll still decides.** Within one short poll (5 seconds by default) the relay shows whatever the Ocelot reports. If the Ocelot really did not switch it, that is where you will see it.
* **If the Ocelot does not acknowledge the command, nothing is claimed**: the state is not sent, and the read updates the relay like any other node, as before.
* **Checked on hardware (SECU-16), from the log:** eight commands, four on relay 7 of unit 1 and four on relay 6 of unit 2 (an On, an Off, an On and an Off on each). Each produced exactly one status change, between 0.08 and 0.41 seconds after the command, with no flip-back and no change from the regular polls that followed, and no warning or error was logged. The installer also reported that it works very well. The two Off commands to relay 6 of unit 2 took about 0.4 seconds to show, against about 0.08 seconds for the other six; why is not known (one possible cause is the Ocelot taking longer to acknowledge them, but the log does not show it). Not covered by that check: an RLY08-XA relay after this change (it was not touched by it), and a relay the Ocelot fails to acknowledge. Only status changes and command times were read from the log; no raw bytes were captured.

## Changed in 1.14.0

* **Placeholder nodes for unsupported expansion modules** (see "Unsupported modules" above). Before this, such modules were only logged and shown in a notice banner.
* The `Ocelot Unsupported Module` node type (no commands, one property) is new in the profile.
* Not tested on hardware: the installer's Ocelot reports only supported types (6, 11 and 13) and empty slots, so no placeholder has been made from a real unsupported module. Hardware-free tests cover it.

## Changed in 1.13.0

* **SECU-16 and SECU-16I modules are now read with Get Latched I/O** (protocol command 50, the request `200,50,0,0,0,0,0,250` published in the protocol document) instead of Get Real Time I/O. This was the installer's request. **RLY08-XA modules are unchanged**: they are still read with Get Real Time I/O on the regular polls.
* **What is read on each poll depends on which modules are installed.** With all three kinds present, a short poll makes three requests, in this order: Get Latched I/O, Get Real Time I/O, then the program variables. With only SECU-16/SECU-16I modules there is no Real Time read; with only RLY08-XA modules there is no Latched read. With no I/O modules at all, one Real Time read is still made, only to check that the Ocelot answers. Every reply is 256 data bytes on the one serial link, so the load is higher than with two requests.
* **After a relay On/Off command only the Latched read is made** (installer's choice), never the Real Time read. The SECU-16 and SECU-16I inputs and relays are refreshed straight away (except the relay just commanded, see 1.15.0). **RLY08-XA relay nodes are not refreshed by that read**: such a node shows the commanded state (if the Ocelot acknowledged the command) until the next regular poll, up to 5 seconds later, which then shows what the Ocelot reports. With no SECU-16 or SECU-16I module installed, a relay command is not followed by any read. As before, the read happens whether or not the command was acknowledged, and not when the port is closed or sending the command raised an error.
* **Reading the latched data clears the latch.** That is as stated by the installer; the protocol document does not say. Effect on the nodes: an input that closed and opened again between two reads shows On for one read, then Off. The input node's DON/DOF events follow the same changes. The read after a relay command clears the latches the same way a poll does.
* **Reply format** (from the protocol document; the installer's Ocelot answered it in the 1.14.0 run, with no "no valid answer" in the log, but the raw bytes were not captured): a 3-byte `6,0,6` header, then 256 data bytes, with no 6-byte header and no CRC (unlike the Real Time and Get Variables replies). The plugin rejects a reply whose first three bytes are not `6,0,6`. For SECU-16 the first data byte holds the latched inputs 0-7 and the second the latched relays 0-7; for SECU-16I the first holds inputs 0-7 and the second inputs 8-15. These are the same byte positions the plugin already used with the Real Time read, so no node changed.
* **The document's RLY08-XA latched layout is not used.** It says the first byte is 0 and the latched relays are in the second byte, which contradicts what was measured on a real RLY08-XA with the Real Time read (relays in the first byte, see "Fixed in 1.8.1"). That is why the RLY08-XA stays on Real Time.
* **If one of the reads gets no answer**, the nodes that the other read supplies are still updated, but the poll counts as failed: the variable read is skipped for that poll, and after three failed polls in a row a notice appears and the plugin reconnects at the next long poll (as before). The log names the read that failed.
* The first Latched read after a plugin restart can show a few points On that are then Off at the next read (seen once on the installer's system: three points, one second apart). It is probably latched history that built up while nothing was reading the latch; that is not confirmed. An input that changes that way also sends a DON then a DOF event.

## Changed in 1.12.0

* **Relay On/Off now reads the inputs and relays immediately afterwards.** As soon as an On or Off command has been sent to the Ocelot, the plugin does an I/O read, so every input node and relay node shows the state the Ocelot reports without waiting for the next poll. In 1.12.0 this was the same Get Real Time I/O read the short poll made; since 1.13.0 it is the Get Latched I/O read only (see above), and since 1.15.0 it leaves the commanded relay itself alone. This matters when switching a relay changes an input, or when a CPU-XA program reacts to the relay.
* The read happens whether or not the Ocelot acknowledged the command: an unacknowledged command may still have taken effect. It does **not** happen when the serial port is not open or when sending the command raised an error (the link is probably down).
* The relay node shows the commanded state (only if the Ocelot acknowledged it). Before 1.15.0 the read then replaced it with the state the Ocelot reported, which could briefly show the old state until the next poll (up to 5 seconds); that is what 1.15.0 fixes for the commanded relay. A failed read leaves the commanded state as it was.
* Only relay On/Off commands do this. IR sends and Write Variable do not read the inputs (Write Variable reads the variables, see 1.11.0).

## Changed in 1.11.0

* **Write Variable now reads all the variables immediately afterwards.** As soon as a write has been sent to the Ocelot, the plugin does a Get Variables read, so **Read Variable**, **Read Value** and **Last Read Result** show what the Ocelot actually holds without waiting for the next poll.
* The follow-up read happens whether or not the Ocelot acknowledged the write: an unacknowledged write may still have taken effect, and the read shows which it was. It does **not** happen when the command had invalid parameters, when the serial port is not open, or when sending the write raised an error (the link is probably down, and a read would only add a timeout).
* **Last Write Result**, **Last Variable** and **Last Value Written** are not changed by the follow-up read. If the read gets no valid answer, only **Last Read Result** shows "No Valid Answer".
* **Read Value** keeps showing the variable chosen with Read Variable, not automatically the one just written. To check a write, select that variable with Read Variable first (since 1.19.0 the written variable's own property, for example **Variable 10**, is also up to date straight away).

## Changed in 1.10.0

* **The program variables are now read on every short poll** (every 5 seconds by default), straight after the relay/input read. The **Read Variable**, **Read Value** and **Last Read Result** properties therefore follow changes made by a CPU-XA program, C-Max or Write Variable within one poll, without having to run Get Variables or Read Variable. Those commands, Query and discovery still read the variables on request as before.
* If the relay/input read in the same poll gets no answer, the variable read is skipped for that poll (the link is probably down, and a second read would only add another timeout).
* Cost: each short poll makes an extra request, and each reply is 264 bytes on the single serial link shared with everything else. On a slow adapter speed this uses a noticeable share of each 5 seconds. The interval is the plugin's short poll setting.
* A variable read made by the poll is logged at debug level only; a failed read is still logged as an error (every poll while it keeps failing).

## Changed in 1.9.2

* **Two variables have new labels in the variable list, both given by the installer:** variable 60 is now "60 Last received IR", and variable 62 is now "62 Beep Duration" (it was "Time Conversion", the name the March 2000 protocol document gives it). Neither wording is from the document. It is wording only: the stored values, commands and existing Programs are unchanged. The labels are part of the node profile, so they appear once the plugin has restarted and re-sent its profile.

## Changed in 1.9.1

* **Input status labels are now Off / On** (they were Inactive / Active), matching the relay nodes. This is wording only: the stored values (0 and 1), the DON/DOF command ids and how `InvertInputs` works are unchanged, so existing Programs keep working. The input node's DON/DOF events, which Programs use as triggers, are now named *On* and *Off* instead of *Active* and *Inactive*. The labels are part of the node profile, so they appear in the admin console and Programs once the plugin has restarted and re-sent its profile (refresh the admin console if the old wording still shows).

## Changed in 1.9.0

* **Program variables can now be read.** The `Ocelot Variables` node has two new commands, **Get Variables** and **Read Variable** (a variable number 0-127), and three new properties: **Last Read Result**, **Read Variable** and **Read Value**. See "Program variables" below for what is and is not known about the command behind them.
* In 1.9.0 the variables were read **only when you asked**: on Get Variables, Read Variable, Query (the controller's, or the Query of the whole plugin) and discovery (which also runs at startup). Since 1.10.0 they are also read on every short poll, and since 1.11.0 right after every write (see above).
* The editor and node definition changed, so the new commands and properties appear in the admin console and Programs once the plugin has restarted and re-sent its profile.
* The earlier README statement that variables cannot be read was wrong for this Ocelot, and has been corrected.

## Changed in 1.8.2

* **Write Variable accepts variable numbers 0-127** (it was 0-63). The range was given by the installer; the March 2000 protocol document lists only 0-63. Values stay 0-65535. Variables 61, 62 and 63 keep the labels the protocol document gives them (see "Program variables"). The editor range is part of the node profile, so the new limit appears in the admin console and Programs once the plugin has restarted and re-sent its profile.

## Fixed in 1.8.1

* **RLY08-XA relays always showed Off when polled**, although switching them worked. The plugin read the relay states from the second data byte of the module's pair; the RLY08-XA reports them in the **first** byte (bit *n* = relay *n*). This was measured on a real module (see "Verified on hardware"). After upgrading, the relay nodes show the real state on the next poll. Only relay nodes of RLY08-XA modules (type 13) are affected; SECU-16 relays are read as before.

## Removed in earlier versions (upgrade notes)

* **1.8.0 removed the `Baud` setting.** It had no effect: for a `socket://` connection pyserial ignores every port setting. A leftover `Baud` entry is deleted automatically, whatever its value.
* **1.7.0 removed the `X10Devices` setting and X-10 support** (X-10 lamp/appliance nodes, sending and receiving). An empty `X10Devices` entry is deleted automatically. If it held a list, the entry is left in place and a notice says it is ignored; clear or delete it yourself. Any Program or scene that used an X-10 node from this plugin will no longer work.
* **1.6.0 removed the `Port` setting** (a device path or a full `socket://host:port` URL). An empty or superseded `Port` entry is deleted automatically. If a `Port` value is still present and `IPAddress` is empty, the value is left in place and a notice asks you to enter IPAddress and IPPort; nothing is converted for you.
* 1.2.0 replaced the single `Mod <unit> IR` node with per-zone nodes (see "SECU-16IR zones").

## IR output

Both kinds of IR output are send-only. **Last Send Result** shows only whether the Ocelot acknowledged the command ("Acknowledged"), not whether a device reacted. **Last IR Number** shows the number last sent successfully. Use either from a Program (Then: *Send IR* / *Send Resident IR*, set IR Number) or from the admin console. This plugin does not learn IR codes; the numbers must already be learned (e.g. with C-Max).

### SECU-16IR zones

The SECU-16IR adds 16 zoned infrared outputs; it has no inputs or relays. Each zone is its own node. Its **Send IR** command sends the protocol's *Send Remote IR Command* (command 92) for that module, that zone and the chosen IR number.

* IR numbers are limited to 0-1023, as stated by the installer. The protocol itself carries a 16-bit number and the protocol document does not give the valid range for a SECU-16IR, so the limit has not been checked against the document.
* Sending to all zones at once (zone 255 in the protocol) is not exposed by these nodes.
* A module is recognised as a SECU-16IR by unit type code 6, which was observed on a real Ocelot with one SECU-16IR installed. The protocol document text does not list type codes, so this rests on that one observation.
* Upgrading from 1.1.x: the old single `Mod <unit> IR` node is removed automatically the first time version 1.2.0 or later discovers the module. Any Programs that used it must be re-pointed at the zone nodes.

### Resident IR (the Ocelot's own IR output)

The `Ocelot Resident IR` node's **Send Resident IR** command sends the protocol's *Send Resident IR* (command 90): the Ocelot transmits the IR command stored under that number in its own memory. It does not use any SECU-16IR.

* The protocol document gives resident IR numbers as 0-39 ("IRnumber (0 to 39)"), so that is the limit here. This is deliberately different from the SECU-16IR zone nodes' 0-1023.
* The node is created whenever the Ocelot answers, whether or not a SECU-16IR is installed.

## Program variables

### Writing

The `Ocelot Variables` node's **Write Variable** command sends the protocol's *Write CPUXA Variable Data* (command 41): it stores a 16-bit **Value** (0-65535) into the chosen **Variable** (0-127) so the Ocelot's own programs can act on it. Use it from a Program (Then: *Write Variable*, set Variable and Value) or from the admin console. The installer tested this on real hardware and reported it works.

Since 1.20.0 each variable's own property (**Variable 0** to **Variable 127**) also has an edit command that does the same write with just a value (see "Changed in 1.20.0" and "Changed in 1.20.2"). In eisyUI, find these inputs in the list of commands at the bottom of the `Ocelot Variables` node page; the **Variable** tiles at the top only display the current values.

* The variable range 0-127 and the value range 0-65535 were given by the installer. The protocol document (March 2000) lists variables 0-63 only, so for variables 64-127 the document has nothing to check against, and no write to one of them has been recorded as tested on hardware.
* The protocol document marks variables 61 (Leopard beep counter: the Leopard beeps that many times, then stops), 62 (time conversion variable) and 63 (Leopard screen number: 0 for a user-loaded bitmap, 1-24 for C-Max designed screens) as special; 0-60 are regular. Variables 61 and 63 keep those labels in the list. Variables 60 and 62 are labelled "60 Last received IR" and "62 Beep Duration" as given by the installer; for 62 this differs from the document's "time conversion variable", and neither label is from the document. The document does not say whether 61-63 are still special on an Ocelot with 128 variables, so only write to them if you know what they do on your system.
* **Last Write Result** shows only whether the Ocelot acknowledged the write ("Acknowledged"); **Last Variable** and **Last Value Written** show the last successful write.
* **Right after the write, all variables are read again** (from 1.11.0), so **Read Value**, **Last Read Result** and (from 1.19.0) the written variable's own property are up to date straight away (see "Reading" below). This read does not change Last Write Result.
* The protocol document does not say whether the 16-bit value is signed. Values are sent as unsigned 0-65535; negative numbers are not accepted.

### Reading

**Get Variables** asks the Ocelot for all 128 variables in one request and keeps them. **Read Variable** takes a variable number (0-127), does a fresh Get Variables read, and shows that variable in **Read Variable** / **Read Value**. **Last Read Result** says "Read OK" if the Ocelot gave a valid answer, or "No Valid Answer" if it gave no answer, a short one, or one with an unexpected header (nothing already shown is overwritten in that case).

* **This command is not in the Applied Digital protocol document.** The request, the 8 bytes `42,0,0,145,170,0,0,166`, was supplied by the installer. The last two bytes of the request cannot be computed from anything in the document, so they are sent exactly as supplied.
* Reply layout, as seen on a real Ocelot: a 6-byte header that repeats the first six bytes of the request, then 256 data bytes, then 2 trailer bytes. The trailer is not interpreted, like the CRC on the other read replies. The plugin rejects a reply whose header differs.
* The 256 data bytes are 128 variables of 16 bits, **least significant byte first**: variable *n* is `data[2n] + 256 * data[2n+1]`. This was checked on the installer's Ocelot, where variable 58 held 999 and variable 59 held 1001; they sat at data bytes 116-119 as `e7 03 e9 03`. This is the same byte order as Write Variable. (The installer had first described the order as most significant byte first; the real reply showed that is not the case.)
* Variables 120-127 were non-zero on that Ocelot (1035, 1, 0, 6, 37, 17, 15, 0). Whether the Ocelot itself updates some variables, such as a clock or counters, has **not** been checked, so do not assume a variable only changes when you write it. In the 1.20.1 log variable 62 alternated between 2 and 65535 every few seconds with no write from this plugin, so at least that variable does change on its own.
* **The variables are read on every short poll** (from 1.10.0), right after the relay/input read, **immediately after every Write Variable** that reached the Ocelot (from 1.11.0), and on Get Variables, Read Variable, Query and discovery. A change made by a CPU-XA program or C-Max is therefore shown within one poll (5 seconds by default); a change made by Write Variable is shown straight away. The poll's variable read is skipped when an I/O read of the same poll got no answer.
* **Every variable has its own property** (from 1.19.0): **Variable 0** to **Variable 127**, filled from each of those reads, so a Program can test any variable directly (see "Changed in 1.19.0"). Since 1.20.0 each also has an edit command.
* **Read Value shows one variable**: the one chosen with Read Variable (variable 0 until you choose). After a write to a different variable, Read Value still shows the chosen one. Use the per-variable properties when you need a specific variable regardless of that selection.
* Two other guessed requests, `11 00 00 00 00 00 00 11` and `24 00 00 00 00 00 00 24`, were tried on the real Ocelot and got no reply. They are not used.
* Only variable values are read: no variable name, and no information on how the Ocelot's own programs use them.
* Only one program can use the Ocelot's connection, so reading briefly occupies the same link as everything else; requests are queued, not sent at the same time.

## Requirements

* The OS account that runs the plugin (`admin` unless `runAs` is changed) must be able to import **`udi_interface` 3.4.7 or newer**. Older versions (for example 3.3.13) lack the Dynamic Profiles API and the plugin crashes at startup with `'Interface' object has no attribute 'updateJsonProfile'`. To upgrade, run as that account:

        pip3 install --user --upgrade 'udi_interface>=3.4.7'

  then restart the plugin.
* `pyserial` (installed by `install.sh` from `requirements.txt`); it provides the `socket://` connection.

## Setup

1. Install, then open the plugin's configuration page.
2. Set **IPAddress** and **IPPort** (see "Connecting to the Ocelot" above and the on-page help).
3. Check that the adapter's serial settings match the Ocelot's (see "Known gaps").
4. Restart or wait a few seconds. Use **Rescan Modules** after adding expansion modules or changing their addresses: it asks the Ocelot itself to re-detect its modules, then looks for them and creates their nodes.

If the connection fails at startup, the plugin retries discovery about once a minute. Notice banners on the configuration page report problems (invalid connection settings, cannot open the connection, Ocelot not answering).

Set the serial-to-Ethernet adapter to raw TCP server mode (not Telnet or RFC 2217). These adapters usually accept one TCP client at a time, so disconnect C-Max or any other client first.

## Verified on hardware

Tested against a real Ocelot through a serial-to-Ethernet adapter (`socket://host:port`, set with IPAddress and IPPort):

* The Ocelot answered Get Unit Type and the plugin created nodes for the SECU-16 (type 11) and RLY08-XA (type 13) modules found, and one module of type 6 (a SECU-16IR). The unit reported 254 for every unused slot (treated here as an empty slot; the protocol document does not define 254).
* **RLY08-XA relay switching** (On/Off commands) works, as reported by the installer.
* **RLY08-XA relay status**: read from the first data byte (Get Real Time I/O). Checked by switching relay 7 of unit 3: that module's first byte was 152 (relays 3, 4 and 7 on) before, and 24 after relay 7 was switched off, while the second byte stayed 0. Only relay 7 was switched during that test, so relays 0-6 rely on the same one-bit-per-relay layout rather than being individually checked. The installer later confirmed the RLY08-XA relays show the right state.
* **SECU-16** (type 11): the layout used here (inputs in the first data byte, relays in the second) was tested by the installer and reported working, **with the Get Real Time I/O read** (before 1.13.0). No raw bytes were captured for it.
* **Get Latched I/O (1.13.0 and later) on SECU-16**: in the log of the 1.14.0 run, the reads were answered with no "no valid answer", all 40 relay/input nodes showed the same states as before the switch from Real Time, and SECU-16 relay commands (relay 7 of unit 2, relay 5 of unit 1) were followed by status changes. This rests on the log only (no raw bytes), and it also showed the stale-state problem that 1.15.0 addresses.
* **SECU-16 relay commands with 1.15.0**: the commanded state stays shown with no flip-back (relay 7 of unit 1 and relay 6 of unit 2, eight commands in all; see "Changed in 1.15.0" for the details and what was not covered). Reported by the installer as working very well; the log agrees.
* **Input polarity**: the installer confirmed the default (`InvertInputs` = `false`, bit 1 shown as On) is correct for their inputs. The protocol document does not say which polarity a closed contact has, so wiring that behaves the other way needs `InvertInputs` = `true`.
* **Variable writes** (Write Variable, command 41): reported working by the installer, with the range 0-127 / 0-65535 stated above. Which variables or values were tried was not recorded.
* **Variable reads** (Get Variables): the frame answered with 264 bytes on a real Ocelot. Variables 58 and 59, which the installer knew to hold 999 and 1001, were found at the matching positions, least significant byte first. The single read captured is what the layout above is based on; the tests rebuild it. A written value read back through this plugin (a write followed by a read) has not been tried on hardware. The plugin log of the installer's system shows the variable table being read every 5 seconds without errors (128 variables, 3 non-zero).
* **Per-variable properties (1.19.0)**: after the restart the installer confirmed that all the variables are shown in the `Ocelot Variables` node. The log of that restart shows the profile accepted and the variable table read every 5 seconds without errors. Using one of them in a Program condition was not reported.
* **Profile delivery (1.20.1, 1.20.2)**: both profile updates were accepted (`success`) and IoX's stored copy holds all 128 properties and all 128 edit commands (with `init` from 1.20.2). At 1.20.2 the installer found the edit inputs in eisyUI's command list at the bottom of the node page. Whether they existed at 1.20.1 was not checked, and no write made through them has been reported yet.
* **Delete Module Nodes (1.16.1)**: two presses on the installer's system each deleted all 34 module nodes, and Discover created them again (from the log). Version 1.16.0 had left 17 behind (see "Changed in 1.16.1").
* **Per-module node types (1.17.0)**: after the restart PG3 held 8 SECU16 Input, 8 SECU16 Relay and 16 SECU16I Input nodes, and the installer confirmed the Type column looks right.
* **The Ocelot on the installer's system** reports unit 2 as type 12 (SECU-16I) and unit 4 as type 11 (SECU-16), so the plugin has now created SECU-16I input nodes on real hardware; whether their input states are right has not been checked here (the README had no SECU-16I to test before).

Not yet confirmed on hardware: **a write made through a variable's edit input reaching the Ocelot (the inputs are there in eisyUI; no write through them was reported; the admin console and UD Mobile were not checked)**; **using a per-variable property in a Program condition (1.19.0)**; **removing the Discover command (1.18.0)**; **placeholder nodes for unsupported module types (1.14.0)**; the SECU-16I input layout; IR sending (remote and resident); reading the variables on every short poll (1.10.0) and the read straight after a variable write (1.11.0); these are covered by hardware-free tests only. The serial settings in use were those of the adapter, which were not recorded here.

## Known gaps: please read

The protocol was taken from Applied Digital's published *CPU-XA Protocol* document (March 2000), plus the installer's Get Variables frame (see "Program variables"). That document:

* does **not** state the serial speed or character format, so they could not be checked against it. Set them on the adapter to match the Ocelot (C-Max's Comms Setup screen shows them).
* does **not** describe the CRC on the "42-type" responses. The CRC bytes are read and ignored, and the last two bytes of the fixed 42-type requests cannot be computed, so those requests are sent exactly as published or supplied. (Get Latched I/O is a 200-type request with a computable checksum and its reply has no CRC.)
* describes the layout of the I/O data only in words (Data1 and Data2 per module type), not which bit belongs to which input or relay. The RLY08-XA and SECU-16 layouts were confirmed on real hardware with the Real Time read (see above), and the document's latched layout for the RLY08-XA contradicts the measured one (so that module is not read with Get Latched I/O); the SECU-16I layout is as the document states and unconfirmed.
* does not say how long a latch holds or what clears it. That reading clears the latch is the installer's statement.
* does not list the unit type codes. Only 6, 11, 12 and 13 are recognised (6 from one observation, the others from the document's module names and the installer's hardware); the meaning of any other code is unknown, which is why those modules only get placeholder nodes.
* has **no command to read program variables**; the Get Variables frame used here is not from the document (see "Program variables"). There is also no command to read analog values. Only the digital bit state is available, so SECU-16 analog inputs are shown as simply On/Off.
* lists variables 0-63 only; the 0-127 range comes from the installer (see "Program variables").
* does not say which input bit polarity means "contact closed": the default was confirmed correct on the installer's system, and `InvertInputs` is there if yours is backwards.

Relay status may be the Ocelot's record of what it last commanded, not a live reading from the module. A 2006 HomeSeer forum post about the Ocelot/Leopard and the RLY8-XA reports exactly that (a locked-up RLY8-XA still being shown as switching). This plugin has not tested that on hardware: if a relay is changed some other way, or a module stops responding, the shown status may be wrong.

Unit numbering is treated as 1-based (the first expansion module is unit 1), consistent with the document's "unit 1" ordering and C-Max's note that module numbering starts at 1. If relay commands hit the wrong module, report it.

Only one program can use the Ocelot's serial connection at a time. Close C-Max before starting the plugin.

## Tests

Protocol logic (frame/checksum building, parsing, unit classification, IR and variable command framing, variable reading and byte order, connection-setting validation), the short-poll sequencing (I/O reads, then variable read; skipped when an I/O read fails), the Get Latched I/O frame, reply format and per-module read selection (`tests/test_ocelot_latched.py`), the write-then-read behaviour of Write Variable, the relay command's forced status and latched-only I/O read that leaves the commanded relay alone (`tests/test_ocelot_relay.py`), the placeholder nodes made by discovery (`tests/test_ocelot_placeholders.py`), the Delete Module Nodes command, including its wait for PG3's pending node adds (`tests/test_ocelot_delete.py`), the per-module node types (`tests/test_ocelot_nodetypes.py`), the per-variable properties and their change-only publishing (`tests/test_ocelot_varprops.py`) and editing a variable property (`tests/test_ocelot_varedit.py`) are covered by hardware-free unit tests:

    python3 -m unittest discover -s tests

Note: with the real `udi_interface` installed, importing it redirects stdout/stderr, so the test runner may print nothing; run the tests with their results written to a file (a `TextTestRunner(stream=open(...))`) to see them.
