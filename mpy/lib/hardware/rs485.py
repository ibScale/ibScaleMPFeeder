# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# rs485.py - Provides RS485 event-based networking

import machine, time, micropython
import application.packetizer as packetizer

DE_PIN_DRIVE, DE_PIN_RECEIVE = 1, 0

class RS485:
    """RS485 communication with interrupt-driven ring buffer and packet validation."""
    
    def __init__(self, slot_id, de_pin_name, uart_id=2, baudrate=9600, data_bits=8, 
                 parity=None, stop_bits=1, rx_buffer_size=None, DMESG=None, LOG=False):
        
        if not (0 <= slot_id <= 254):
            raise ValueError("Slot ID must be between 0 and 254.")
        
        self._slot_id, self._dmesg, self._log_debug = slot_id, DMESG, LOG
        self._de_pin_name, self._uart_id, self._baudrate = de_pin_name, uart_id, baudrate
        self._logger_func = self._dmesg.log if self._dmesg else print

        # Calculate buffer size
        if rx_buffer_size in (None, 0):
            bits_per_byte = 1 + data_bits + (0 if parity is None else 1) + stop_bits
            calculated_size = int((baudrate / bits_per_byte) * 0.100) * 2  # 100ms * 2
            power = 128  # min size
            while power < calculated_size: power *= 2
            self._rx_buffer_size = power
        else:
            self._rx_buffer_size = rx_buffer_size

        # Initialize ring buffer
        self._rx_buffer = bytearray(self._rx_buffer_size)
        self._rx_head = self._rx_tail = self._rx_count = 0
        self._uart = self._de_pin = None

        try:
            # Setup hardware
            self._de_pin = machine.Pin(de_pin_name, machine.Pin.OUT)
            self._de_pin.value(DE_PIN_RECEIVE)
            self._uart = machine.UART(uart_id, baudrate=baudrate, bits=data_bits, 
                                     parity=parity, stop=stop_bits, timeout=10, timeout_char=5)
            self._uart.irq(trigger=machine.UART.IRQ_RXIDLE, handler=self._uart_irq_handler)
            
            parity_str = "None" if parity is None else str(parity)
            self._log(f"Init - UART={uart_id}, Baud={baudrate}, Bits={data_bits}, Parity={parity_str}, Stop={stop_bits}, DE='{de_pin_name}', RxBuf={self._rx_buffer_size}, IRQ=RXIDLE")

        except Exception as e:
            self._log(f"ERROR initializing: {e}")
            if self._uart: self._uart.deinit()
            if self._de_pin:
                try: self._de_pin.deinit()
                except: pass
            raise

    def _log(self, msg, debug=False):
        if not debug or self._log_debug:
            self._logger_func(f"RS485: {msg}")

    def _uart_irq_handler(self, uart):
        data = uart.read()
        if data: micropython.schedule(self._process_incoming_data, data)

    @micropython.native
    def _process_incoming_data(self, data):
        validated_data = packetizer.validate_packet(data, self._slot_id, self._logger_func, self._log_debug)
        if not validated_data: return

        data_len = len(validated_data)
        irq_state = machine.disable_irq()
        added = False
        try:
            if self._rx_count + data_len <= self._rx_buffer_size:
                for byte in validated_data:
                    self._rx_buffer[self._rx_head] = byte
                    self._rx_head = (self._rx_head + 1) % self._rx_buffer_size
                self._rx_count += data_len
                added = True
        finally:
            machine.enable_irq(irq_state)

        if not added:
            self._log(f"ERROR: RX Buffer Overflow! Discarding {data_len} bytes")
        elif self._log_debug:
            self._log(f"Added {data_len} bytes. Count={self._rx_count}", debug=True)

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
            self._de_pin.value(DE_PIN_RECEIVE)
            self._uart.irq(trigger=machine.UART.IRQ_RXIDLE, handler=self._uart_irq_handler)

    def send_packet(self, packet):
        if not packet or not isinstance(packet, (bytes, bytearray)):
            self._log("ERROR: Invalid packet")
            return False
        self.send(packet)
        return True

    def _peek_byte(self, offset):
        if offset >= self._rx_count: return None
        return self._rx_buffer[(self._rx_tail + offset) % self._rx_buffer_size]

    def _get_next_packet_length(self):
        if self._rx_count < packetizer.MIN_HEADER_LEN: return 0
        payload_len = self._peek_byte(packetizer.IDX_PAYLOAD_LEN)
        if payload_len is None or payload_len < packetizer.MIN_PAYLOAD_LEN: return 0
        return packetizer.MIN_HEADER_LEN + payload_len

    def any(self):
        irq_state = machine.disable_irq()
        try:
            if self._rx_count >= packetizer.MIN_TOTAL_PACKET_LEN:
                expected_len = self._get_next_packet_length()
                return expected_len > 0 and self._rx_count >= expected_len
            return False
        finally:
            machine.enable_irq(irq_state)

    @micropython.native
    def read_packet(self):
        raw_packet = None
        discarded = False

        irq_state = machine.disable_irq()
        try:
            expected_len = self._get_next_packet_length()
            
            if expected_len > 0 and self._rx_count >= expected_len:
                result = bytearray(expected_len)
                tail = self._rx_tail
                for i in range(expected_len):
                    result[i] = self._rx_buffer[tail]
                    tail = (tail + 1) % self._rx_buffer_size
                
                self._rx_tail = tail
                self._rx_count -= expected_len
                raw_packet = bytes(result)
                
            elif expected_len == 0 and self._rx_count >= packetizer.MIN_HEADER_LEN:
                self._rx_tail = (self._rx_tail + 1) % self._rx_buffer_size
                self._rx_count -= 1
                discarded = True
        finally:
            machine.enable_irq(irq_state)

        if discarded:
            self._log("Discarded invalid header byte", debug=True)

        if raw_packet:
            if self._log_debug:
                self._log(f"Read packet ({len(raw_packet)} bytes). Buffer={self._rx_count}", debug=True)
            
            parsed = packetizer.parse_packet(raw_packet)
            if parsed:
                if self._log_debug:
                    self._log(f"Parsed: TO={parsed['to']:#04x}, FROM={parsed['from']:#04x}, CMD={parsed['cmd']:#04x}", debug=True)
                return parsed
            else:
                self._log(f"ERROR: Parse failed: {raw_packet}")
        return None

    def clear_rx_buffer(self):
        irq_state = machine.disable_irq()
        self._rx_head = self._rx_tail = self._rx_count = 0
        machine.enable_irq(irq_state)
        self._log("RX buffer cleared")

    def deinit(self):
        self._log("Deinitializing")
        if self._uart:
            self._uart.irq(None)
            self._uart.deinit()
            self._uart = None
        if self._de_pin:
            try:
                self._de_pin.value(DE_PIN_RECEIVE)
                self._de_pin.deinit()
            except: pass
            self._de_pin = None
        self.clear_rx_buffer()