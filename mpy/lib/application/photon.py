# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# photon.py - Photon feeder protocol state machine.
#
# Implements the Opulo/LumenPNP Photon protocol (https://docs.opulo.io/misc/photon/)
# on top of the RS485 network layer (application.packetizer) and the software servo.
# Commands are dispatched from update(), which the main app loop calls each tick.
#
# Move model: MOVE_FEED_* replies immediately with OK + expected time (ms), then runs
# the feed as a real-time burst (servo.run_move) to completion. The feeder is briefly
# unresponsive during the feed - matching the spec's "the feeder blocks during feeding".
# MOVE_FEED_STATUS returns the stored result; FEEDING_IN_PROGRESS is therefore not used.

import time
from ubinascii import unhexlify
import application.packetizer as pkt
from system.servo import RESULT_REACHED, RESULT_OVERSHOT, RESULT_STALLED, RESULT_TIMEOUT

_PROTOCOL_VERSION = 1
_UUID_LEN = 12
_DISCOVERY_WINDOW_MS = 250  # UUID-seeded jitter window for broadcast discovery replies


class Photon:
    def __init__(self, network, dmesg, servo, led, sysconfig, eeprom=None,
                 node_address=0, uuid=None):
        self.net = network
        self.dmesg = dmesg
        self.servo = servo
        self.led = led
        self.sysconfig = sysconfig
        self.eeprom = eeprom
        self.address = node_address & 0xFF
        self._initialized = False
        self._last_move_result = pkt.RESP_OK

        self.ticks_per_010mm = sysconfig.get('SYSTEM.TICKS_010MM', 22.546)
        self.slot_profile = sysconfig.get('SYSTEM.SLOT_PROFILE', 'normal')
        self.uuid_bytes = self._coerce_uuid(uuid)
        self._discovery_delay_ms = self._discovery_delay()

        self._handlers = {
            pkt.CMD_GET_FEEDER_ID: self._h_get_id,
            pkt.CMD_INITIALIZE_FEEDER: self._h_initialize,
            pkt.CMD_GET_VERSION: self._h_version,
            pkt.CMD_MOVE_FEED_FORWARD: self._h_move_forward,
            pkt.CMD_MOVE_FEED_BACKWARD: self._h_move_backward,
            pkt.CMD_MOVE_FEED_STATUS: self._h_status,
            pkt.CMD_GET_FEEDER_ADDRESS: self._h_get_address,
            pkt.CMD_IDENTIFY_FEEDER: self._h_identify,
            pkt.CMD_PROGRAM_FEEDER_FLOOR: self._h_program_floor,
            pkt.CMD_UNINITIALIZED_FEEDERS_RESPOND: self._h_uninit_respond,
            pkt.CMD_VENDOR_OPTIONS: self._h_vendor,
        }
        self._log(f"Ready - addr={self.address}, uuid={self.uuid_bytes.hex()}, "
                  f"disc_delay={self._discovery_delay_ms}ms", force=True)

    def _log(self, msg, force=False):
        if self.dmesg:
            self.dmesg.log(f"PHOTON: {msg}")

    def _discovery_delay(self):
        """Deterministic per-feeder reply delay (FNV-1a over the UUID), spread across
        _DISCOVERY_WINDOW_MS, so multiple uninitialized feeders don't transmit their
        UNINITIALIZED_FEEDERS_RESPOND replies at the same instant and collide on the bus."""
        h = 2166136261
        for b in self.uuid_bytes:
            h = ((h ^ b) * 16777619) & 0xFFFFFFFF
        return h % _DISCOVERY_WINDOW_MS

    def _coerce_uuid(self, uuid):
        if uuid is None:
            return b'\x00' * _UUID_LEN
        if isinstance(uuid, str):
            try:
                ub = unhexlify(uuid)
            except Exception:
                ub = uuid.encode()
        else:
            ub = bytes(uuid)
        return (ub + b'\x00' * _UUID_LEN)[:_UUID_LEN]

    # --- Main-loop hook ---------------------------------------------------

    def update(self):
        """Drain and dispatch all pending packets. Called once per app-loop tick."""
        handled = False
        packet = self.net.read_packet()
        while packet:
            handler = self._handlers.get(packet['cmd'])
            if handler:
                try:
                    handler(packet)
                except Exception as e:
                    self._log(f"Handler error (cmd={packet['cmd']:#04x}): {e}", force=True)
            handled = True
            packet = self.net.read_packet()
        return handled

    # --- Helpers ----------------------------------------------------------

    def _reply(self, packet, status, payload=b''):
        resp = pkt.format_packet(packet['from'], self.address, packet['id'], status, payload)
        if resp:
            self.net.send_packet(resp)

    def _uuid_matches(self, payload):
        return len(payload) >= _UUID_LEN and payload[:_UUID_LEN] == self.uuid_bytes

    def _map_result(self, r):
        if r == RESULT_REACHED or r == RESULT_OVERSHOT:
            return pkt.RESP_OK
        if r == RESULT_STALLED or r == RESULT_TIMEOUT:
            return pkt.RESP_COULDNT_REACH
        return pkt.RESP_UNKNOWN

    def _expected_time_ms(self, ticks):
        t = 250 + abs(ticks)         # generous upper bound; reply precedes the move
        return t if t < 65535 else 65535

    # --- Command handlers -------------------------------------------------

    def _h_get_id(self, packet):
        self._reply(packet, pkt.RESP_OK, self.uuid_bytes)

    def _h_initialize(self, packet):
        if self._uuid_matches(packet['payload']):
            self._initialized = True
            self._log("Initialized by host.")
            self._reply(packet, pkt.RESP_OK, self.uuid_bytes)
        else:
            self._reply(packet, pkt.RESP_WRONG_FEEDER_ID, self.uuid_bytes)

    def _h_version(self, packet):
        self._reply(packet, pkt.RESP_OK, bytes([_PROTOCOL_VERSION]))

    def _h_move_forward(self, packet):
        self._move(packet, True)

    def _h_move_backward(self, packet):
        self._move(packet, False)

    def _move(self, packet, forward):
        if not self._initialized:
            self._reply(packet, pkt.RESP_UNINITIALIZED_FEEDER)
            return
        payload = packet['payload']
        if not payload:
            self._reply(packet, pkt.RESP_FAIL)
            return
        tenths = payload[0]
        ticks = int(round(tenths * self.ticks_per_010mm))
        expected = self._expected_time_ms(ticks)
        # Reply OK + expected time first, then run the feed to completion (RT burst).
        self._reply(packet, pkt.RESP_OK, bytes([(expected >> 8) & 0xFF, expected & 0xFF]))
        self.servo.feed(ticks if forward else -ticks, profile=self.slot_profile)
        result = self.servo.run_move()
        self._last_move_result = self._map_result(result)
        self._log(f"Move {'fwd' if forward else 'rev'} {tenths}/10mm ({ticks}t) -> {self.servo.result_name}")

    def _h_status(self, packet):
        if not self._initialized:
            self._reply(packet, pkt.RESP_UNINITIALIZED_FEEDER)
            return
        self._reply(packet, self._last_move_result)

    def _h_get_address(self, packet):
        # Broadcast; reply (FROM our slot, which is how the host learns our address)
        # only when the UUID matches so other feeders stay silent.
        if self._uuid_matches(packet['payload']):
            self._reply(packet, pkt.RESP_OK)

    def _h_identify(self, packet):
        if self._uuid_matches(packet['payload']):
            if self.led:
                try:
                    self.led.blink('blue', count=6)
                except Exception:
                    pass
            self._reply(packet, pkt.RESP_OK)

    def _h_program_floor(self, packet):
        payload = packet['payload']
        if not self._uuid_matches(payload) or len(payload) < _UUID_LEN + 1:
            return  # not us / malformed -> stay silent
        new_addr = payload[_UUID_LEN]
        ok = self._set_address(new_addr)
        self._reply(packet, pkt.RESP_OK if ok else pkt.RESP_FAIL)

    def _h_uninit_respond(self, packet):
        if not self._initialized:
            # Every uninitialized feeder answers this broadcast, so stagger replies by a
            # UUID-seeded delay to avoid bus collisions (host retries cover residual ones).
            time.sleep_ms(self._discovery_delay_ms)
            self._reply(packet, pkt.RESP_OK, self.uuid_bytes)

    def _h_vendor(self, packet):
        if not self._initialized:
            self._reply(packet, pkt.RESP_UNINITIALIZED_FEEDER)
            return
        # No vendor-specific options implemented; acknowledge with empty payload.
        self._reply(packet, pkt.RESP_OK)

    # --- Address programming ----------------------------------------------

    def _set_address(self, addr):
        """Persist a newly programmed floor address to EEPROM + sysconfig and update
        the RS485 RX filter so the feeder answers on its new slot."""
        try:
            addr &= 0xFF
            if self.eeprom:
                self.eeprom.write_memory(0, bytes([addr]))
            self.sysconfig.set('SYSTEM.SLOTID', addr)
            self.sysconfig.save()
            if hasattr(self.net, 'set_slot_id'):
                self.net.set_slot_id(addr)
            self.address = addr
            self._log(f"Floor address programmed to {addr}.", force=True)
            return True
        except Exception as e:
            self._log(f"Address program failed: {e}", force=True)
            return False
