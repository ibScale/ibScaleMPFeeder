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
_VENDOR_OPTIONS_LEN = 20    # VENDOR_SPECIFIC_OPTIONS_LENGTH in the reference firmware
_IDENTIFY_MS = 3000         # how long the identify flash (solid blue) is shown


class Photon:
    def __init__(self, network, dmesg, servo, led, sysconfig, eeprom=None,
                 node_address=255, uuid=None):
        self.net = network
        self.dmesg = dmesg
        self.servo = servo
        self.led = led
        self.sysconfig = sysconfig
        self.eeprom = eeprom
        self.address = node_address & 0xFF
        self.debug_enabled = sysconfig.get('SYSTEM.DEBUG', False)
        self._initialized = False
        self._last_move_result = pkt.RESP_OK
        self._identify_restore = None   # color() to restore once the identify flash ends
        self._identify_until = 0

        # Photon state machine has taken over LED status duty from the boot default
        # (purple, set by RGBLED.__init__) - yellow until CMD_INITIALIZE_FEEDER succeeds.
        if self.led:
            self.led.state('waiting')

        self.ticks_per_010mm = sysconfig.get('SYSTEM.TICKS_010MM', 22.546)
        self.slot_profile = sysconfig.get('SYSTEM.SLOT_PROFILE', 'normal')
        self.uuid_bytes = self._coerce_uuid(uuid)

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
        self._log(f"Ready - addr={self.address}, uuid={self.uuid_bytes.hex()}", force=True)

    @property
    def initialized(self):
        return self._initialized

    def _log(self, msg, force=False):
        if (self.debug_enabled or force) and self.dmesg:
            self.dmesg.log(f"PHOTON: {msg}")

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

    def _next_packet(self):
        """Pull the next valid packet addressed to us from the transport. The
        transport is protocol-agnostic (raw RXIDLE bursts, one per transmission -
        see hardware/rs485.py); validation (length/address/command/CRC) and parsing
        belong to the protocol layer, here."""
        chunk = self.net.read_chunk()
        while chunk is not None:
            valid = pkt.validate_packet(chunk, self.address,
                                        self.dmesg.log if self.dmesg else None,
                                        self.debug_enabled)
            if valid:
                parsed = pkt.parse_packet(valid)
                if parsed:
                    return parsed
            chunk = self.net.read_chunk()
        return None

    def update(self):
        """Drain and dispatch all pending packets. Called once per app-loop tick."""
        self._poll_identify()
        handled = False
        packet = self._next_packet()
        while packet:
            handler = self._handlers.get(packet['cmd'])
            if handler:
                try:
                    handler(packet)
                except Exception as e:
                    self._log(f"Handler error (cmd={packet['cmd']:#04x}): {e}", force=True)
            handled = True
            packet = self._next_packet()
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

    def _poll_identify(self):
        """Non-blocking: once _IDENTIFY_MS has elapsed, revert the identify flash (solid
        blue) back to whatever color was showing before it. Checked once per tick here
        rather than in led.py, which only exposes color()/blink() and has no timers of
        its own."""
        if self._identify_restore is not None and time.ticks_diff(time.ticks_ms(), self._identify_until) >= 0:
            if self.led:
                self.led.color(self._identify_restore)
            self._identify_restore = None

    # --- Command handlers -------------------------------------------------

    def _h_get_id(self, packet):
        self._reply(packet, pkt.RESP_OK, self.uuid_bytes)

    def _h_initialize(self, packet):
        if self._uuid_matches(packet['payload']):
            self._initialized = True
            # Re-anchor the commanded grid: the tape may have been handled/reloaded
            # since the last move, and the first feed must not "correct" that offset.
            self.servo.reseed()
            if self.led:
                self.led.state('ready')
            self._log("Initialized by host.", force=True)
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
            # Reference firmware includes the UUID in the uninitialized error reply.
            self._reply(packet, pkt.RESP_UNINITIALIZED_FEEDER, self.uuid_bytes)
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
        # Cyan while the move is running; restores whatever color() was showing before it
        # once the move stops (if a blink is active, e.g. the console-open indicator, it
        # keeps blinking throughout - it just follows color()).
        prev_color = self.led.current_color if self.led else None
        if self.led:
            self.led.state('feeding')
        self.servo.feed(ticks if forward else -ticks, profile=self.slot_profile)
        result = self.servo.run_move()
        if self.led:
            self.led.color(prev_color)
        self._last_move_result = self._map_result(result)
        if result == RESULT_STALLED or result == RESULT_TIMEOUT:
            # Fault ends the move short and the operator will clear the jam by hand,
            # so the commanded grid no longer means anything. Re-anchor it to the
            # actual position: a retried feed then advances exactly one pitch instead
            # of pitch + the missed distance (which would over-feed past the jam).
            self.servo.reseed()
        # Drop any packets that arrived while the move blocked (e.g. host retries) -
        # matches the reference firmware's clearPackets() after feedDistance();
        # processing them late could replay a MOVE and double-feed.
        while self.net.read_chunk() is not None:
            pass
        self._log(f"Move {'fwd' if forward else 'rev'} {tenths}/10mm ({ticks}t) -> {self.servo.result_name}")

    def _h_status(self, packet):
        # No initialized-guard, matching the reference firmware: the stored result
        # is returned unconditionally.
        self._reply(packet, self._last_move_result)

    def _h_get_address(self, packet):
        # Broadcast; reply (FROM our slot, which is how the host learns our address)
        # only when the UUID matches so other feeders stay silent. Status-only reply,
        # no payload - matching the reference firmware.
        if self._uuid_matches(packet['payload']):
            self._reply(packet, pkt.RESP_OK)

    def _h_identify(self, packet):
        if self._uuid_matches(packet['payload']):
            if self.led:
                self._identify_restore = self.led.current_color
                self.led.state('identify')
                self._identify_until = time.ticks_add(time.ticks_ms(), _IDENTIFY_MS)
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
            # Immediate reply, like the reference firmware: with multiple uninitialized
            # feeders the responses can collide, and the host's retries sort it out.
            self._reply(packet, pkt.RESP_OK, self.uuid_bytes)

    def _h_vendor(self, packet):
        if not self._initialized:
            self._reply(packet, pkt.RESP_UNINITIALIZED_FEEDER, self.uuid_bytes)
            return
        # No vendor-specific options implemented; the reference firmware replies OK
        # with a fixed 20-byte options block (VENDOR_SPECIFIC_OPTIONS_LENGTH).
        self._reply(packet, pkt.RESP_OK, bytes(_VENDOR_OPTIONS_LEN))

    # --- Address programming ----------------------------------------------

    def _set_address(self, addr):
        """Persist a newly programmed floor address to EEPROM + sysconfig and update
        the RS485 RX filter so the feeder answers on its new slot."""
        try:
            addr &= 0xFF
            if addr == 0 or addr == 0xFF:
                # Reserved: 0 is the host's bus address, 0xFF is broadcast. Refuse
                # before anything is persisted (a 0xFF would otherwise land in the
                # EEPROM and then fail the RS485 filter update partway through).
                self._log(f"Refusing reserved floor address {addr}.", force=True)
                return False
            if self.eeprom:
                # write_memory is verified (read-back compare); a failed persist must
                # fail the command - otherwise the new address evaporates on reboot.
                if not self.eeprom.write_memory(0, bytes([addr])):
                    self._log("Address program failed: EEPROM write did not verify.", force=True)
                    return False
            self.sysconfig.set('SYSTEM.SLOTID', addr)
            self.sysconfig.save()
            # self.address is the RX filter (validation happens in _next_packet),
            # so updating it re-addresses the feeder immediately.
            self.address = addr
            self._log(f"Floor address programmed to {addr}.", force=True)
            return True
        except Exception as e:
            self._log(f"Address program failed: {e}", force=True)
            return False
