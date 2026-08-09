# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# rs485.py - RS485 transport: interrupt-driven, chunk-oriented, protocol-agnostic.
#
# The UART's RXIDLE interrupt frames bus traffic into bursts ("chunks"): one chunk
# per transmission burst, which for well-formed half-duplex traffic means one chunk
# per packet. Chunks are queued raw and handed unmodified to whoever owns the
# protocol (see application/photon.py + application/packetizer.py) - this layer
# knows nothing about packet formats, addressing, or CRCs, so the protocol stack
# can be swapped without touching the transport. TX asserts the DE pin around a
# blocking write and re-arms RX afterwards.

import machine, time

DE_PIN_DRIVE, DE_PIN_RECEIVE = 1, 0


class RS485:
    """Half-duplex RS485 byte transport with an interrupt-fed RX chunk queue.

    Contract for protocol layers: read_chunk() -> bytes|None (oldest burst first),
    send_packet(bytes) -> bool. Nothing else is required.
    """

    def __init__(self, de_pin_name, uart_id=2, baudrate=9600, data_bits=8,
                 parity=None, stop_bits=1, max_chunks=16, DMESG=None, LOG=False):
        self._dmesg, self._log_debug = DMESG, LOG
        self._de_pin_name, self._uart_id, self._baudrate = de_pin_name, uart_id, baudrate
        self._logger_func = self._dmesg.log if self._dmesg else print

        # RX queue of raw RXIDLE bursts, ring-style: bounded so a slow/absent
        # consumer (manual mode, or a protocol blocked in a long move) can't grow
        # the heap, dropping the OLDEST burst on overflow so the freshest traffic
        # survives. Overflow is normal on a shared bus with no consumer (all
        # feeders' traffic lands here now that the transport is protocol-agnostic),
        # so it's only logged in debug.
        self._rx_chunks = []
        self._max_chunks = max_chunks
        self._uart = self._de_pin = None

        try:
            self._de_pin = machine.Pin(de_pin_name, machine.Pin.OUT)
            self._de_pin.value(DE_PIN_RECEIVE)
            self._uart = machine.UART(uart_id, baudrate=baudrate, bits=data_bits,
                                      parity=parity, stop=stop_bits, timeout=10, timeout_char=5)
            self._uart.irq(trigger=machine.UART.IRQ_RXIDLE, handler=self._uart_irq_handler)

            parity_str = "None" if parity is None else str(parity)
            self._log(f"Init - UART={uart_id}, Baud={baudrate}, Bits={data_bits}, " +
                      f"Parity={parity_str}, Stop={stop_bits}, DE='{de_pin_name}', " +
                      f"MaxChunks={max_chunks}, IRQ=RXIDLE")

        except Exception as e:
            self._log(f"ERROR initializing: {e}")
            if self._uart: self._uart.deinit()
            if self._de_pin:
                try: self._de_pin.deinit()
                except Exception: pass
            raise

    def _log(self, msg, debug=False):
        if not debug or self._log_debug:
            self._logger_func(f"RS485: {msg}")

    # --- RX -----------------------------------------------------------------

    def _uart_irq_handler(self, uart):
        # UART.irq() here is registered without hard=True, so MicroPython dispatches
        # this deferred/scheduled (mp_sched_schedule), not from the true hardware
        # ISR - allocation is safe here.
        data = uart.read()
        if not data:
            return
        dropped = False
        irq_state = machine.disable_irq()
        try:
            if len(self._rx_chunks) >= self._max_chunks:
                self._rx_chunks.pop(0)
                dropped = True
            self._rx_chunks.append(data)
        finally:
            machine.enable_irq(irq_state)
        if self._log_debug:
            if dropped:
                self._log("RX queue full - dropped oldest burst", debug=True)
            self._log(f"Queued {len(data)} byte burst ({len(self._rx_chunks)} pending)", debug=True)

    def read_chunk(self):
        """Return the oldest received burst as bytes, or None if the queue is empty."""
        irq_state = machine.disable_irq()
        try:
            return self._rx_chunks.pop(0) if self._rx_chunks else None
        finally:
            machine.enable_irq(irq_state)

    # --- TX -----------------------------------------------------------------

    def send(self, data):
        if not self._uart or not self._de_pin:
            self._log("ERROR: Cannot send, not initialized")
            return

        if self._log_debug:
            self._log(f"Sending {len(data)} bytes", debug=True)

        self._uart.irq(None)
        self._de_pin.value(DE_PIN_DRIVE)
        time.sleep_us(20)

        try:
            self._uart.write(data)
            timeout_ms = 100 + (len(data) * 10 * 1000 // self._baudrate)
            start = time.ticks_ms()

            while not self._uart.txdone():
                if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                    self._log("ERROR: TX timeout")
                    break
                time.sleep_us(10)
        except Exception as e:
            self._log(f"ERROR during send: {e}")
        finally:
            time.sleep_us(20)
            # Guard against a concurrent deinit() having torn down the hardware.
            if self._de_pin:
                self._de_pin.value(DE_PIN_RECEIVE)
            if self._uart:
                self._uart.irq(trigger=machine.UART.IRQ_RXIDLE, handler=self._uart_irq_handler)

    def send_packet(self, packet):
        if not packet or not isinstance(packet, (bytes, bytearray)):
            self._log("ERROR: Invalid packet")
            return False
        self.send(packet)
        return True
