## 2026-10-31T16:25:54.356082+00:00

Initial generation: Ocelot (CPU-XA) plugin. Protocol from Applied Digital CPU-XA Protocol document (extracted from PDF on host). Controller + relay/input/x10dev nodes; polling via Get Real Time I/O; X-10 TX/RX; pure-function protocol module with unit tests. Baud/CRC/variable-read unspecified in source, flagged in README.

Sources consulted: Ocelot by Applied Digital inc - LinuxMCE, Adicon Serial Protocols, User's Manual - Applied Digital, Inc., Ocelot™ User’s Guide 1 Ocelot Manual Table of Contents 1, Applied Digital Ocelot Home Automation Controller, Applied Digital ADICON 2500 SECU-16 I/O Module - Home Controls, ADICON™ 2500 and C-Max™ Control Wizard User’s Guide Page 1, ECS: Supported Devices, Ocelot, cdn.shopify.com, CPU-XA Instruction and Program Formats, 1. Serial Protocol v4, IOT Relay Programing Manual V1.9.4, X-SEL Serial Communication Protocol Specification ( ..., Open Source Interface to CPU-XA or Ocelot - Applied Digital, Inc, Section 3 - X10 FAQ

## 2026-11-20T20:10:49.379388+00:00

1.21.0: Send Resident IR now accepts IR numbers 0-1023 (was 0-39), the same as the SECU-16IR zones' Send IR, as stated by the installer. Applied Digital's Ocelot manual and a HomeSeer forum post both describe the Ocelot's IR locations as 0-1023, sendable through its own emitter or a SECU-16IR, which agrees; the protocol document's 0-39 for Send Resident IR was not reconciled with them. RESIDENT_IR_MAX = IR_NUMBER_MAX in ocelot_proto.py; the ocelot_resident_ir editor range is now 0-1023. Proto tests updated (frames at 40, 256, 1023; limit checks at -1 and 1024). README rebuilt from the on-disk README, so generation_inputs.json no longer holds the older README text.

Sources consulted: GTS CPUXA Ocelot Software Plugin for HS3, Need help with IR - HomeSeer Message Board, How to use previously learned Ocelot infrared codes? - HomeSeer Message Board, C-Max™ Software for the Leopard, Ocelot and CPU-XA, CPU-XA Instruction and Program Formats, User Manual

