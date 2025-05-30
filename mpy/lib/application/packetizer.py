# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# packetizer.py - Photon protocol packetizer
# This receives and sends packets including validating and generating them

import micropython

# --- Protocol Constants ---
IDX_TO_ADDR = 0
IDX_FROM_ADDR = 1
IDX_PACKET_ID = 2
IDX_PAYLOAD_LEN = 3 # Number of bytes in payload (starting from CMD at index 5)
IDX_CRC = 4
IDX_CMD = 5 # Start of payload
MIN_HEADER_LEN = 5 # To, From, ID, Length, CRC
MIN_PAYLOAD_LEN = 1 # Payload must include at least CMD byte
MIN_TOTAL_PACKET_LEN = MIN_HEADER_LEN + MIN_PAYLOAD_LEN # 6 bytes
BROADCAST_ADDR = 0xFF

# --- Command Codes (Payload Byte 5) ---
CMD_GET_FEEDER_ID = 0x01
CMD_INITIALIZE_FEEDER = 0x02
CMD_GET_VERSION = 0x03
CMD_MOVE_FEED_FORWARD = 0x04
CMD_MOVE_FEED_BACKWARD = 0x05
CMD_MOVE_FEED_STATUS = 0x06
CMD_VENDOR_OPTIONS = 0xBF
CMD_GET_FEEDER_ADDRESS = 0xC0
CMD_IDENTIFY_FEEDER = 0xC1
CMD_PROGRAM_FEEDER_FLOOR = 0xC2
CMD_UNINITIALIZED_FEEDERS_RESPOND = 0xC3

# Command Codes Lookup Table
VALID_COMMANDS = {
    CMD_GET_FEEDER_ID,
    CMD_INITIALIZE_FEEDER,
    CMD_GET_VERSION,
    CMD_MOVE_FEED_FORWARD,
    CMD_MOVE_FEED_BACKWARD,
    CMD_MOVE_FEED_STATUS,
    CMD_VENDOR_OPTIONS,
    CMD_GET_FEEDER_ADDRESS,
    CMD_IDENTIFY_FEEDER,
    CMD_PROGRAM_FEEDER_FLOOR,
    CMD_UNINITIALIZED_FEEDERS_RESPOND
}

# --- Response Codes ---
RESP_OK = 0x00
RESP_WRONG_FEEDER_ID = 0x01
RESP_COULDNT_REACH = 0x02
RESP_UNINITIALIZED_FEEDER = 0x03
RESP_FEEDING_IN_PROGRESS = 0x04
RESP_FAIL = 0x05
RESP_TIMEOUT = 0xFE
RESP_UNKNOWN = 0xFF

@micropython.viper
def calcCRC8(data_ptr: ptr8, length: int) -> int:
    """Calculate 8-bit CRC checksum."""
    crc = 0
    for i in range(length):
        byte = int(data_ptr[i])
        crc ^= (byte << 8)
        for _ in range(8):
            crc = (crc << 1) ^ (0x1070 << 3) if (crc & 0x8000) else crc << 1
    return ((crc >> 8) & 0xFF)

@micropython.native
def validate_packet(data: bytes, node_slot_id: int, logger=None, log_debug: bool = False) -> bytes | None:
    """Validate raw data against Photon protocol rules."""
    
    def _log(msg: str, debug: bool = False):
        if logger and (not debug or log_debug):
            logger(f"VALIDATE: {msg}")
        elif not debug and not logger:
            print(f"VALIDATE: {msg}")

    data_len = len(data)
    
    # Length checks
    if data_len < MIN_TOTAL_PACKET_LEN:
        _log(f"Too short: {data_len} < {MIN_TOTAL_PACKET_LEN}")
        return None
    
    payload_len = data[IDX_PAYLOAD_LEN]
    if payload_len < MIN_PAYLOAD_LEN:
        _log(f"Invalid payload len: {payload_len}")
        return None
    
    expected_len = MIN_HEADER_LEN + payload_len
    if data_len != expected_len:
        _log(f"Length mismatch: {data_len} != {expected_len}")
        return None
    
    # Address check
    to_addr = data[IDX_TO_ADDR]
    if to_addr != node_slot_id and to_addr != BROADCAST_ADDR:
        if log_debug:
            _log(f"Wrong addr: {to_addr:#04x} (node:{node_slot_id:#04x})", True)
        return None
    
    # Command check
    cmd = data[IDX_CMD]
    if cmd not in VALID_COMMANDS:
        _log(f"Invalid cmd: {cmd:#04x}")
        return None
    
    # CRC check
    crc_data = data[:IDX_CRC] + data[IDX_CMD:IDX_CMD + payload_len]
    calc_crc = calcCRC8(crc_data, len(crc_data))
    recv_crc = data[IDX_CRC]
    
    if calc_crc != recv_crc:
        _log(f"CRC fail: calc={calc_crc:#04x}, recv={recv_crc:#04x}")
        return None
    
    if log_debug:
        _log(f"Valid: {data_len}B, TO={to_addr:#04x}, CMD={cmd:#04x}", True)
    
    return data

def parse_packet(packet_data: bytes) -> dict | None:
    """Parse validated packet into components."""
    if not packet_data or len(packet_data) < MIN_TOTAL_PACKET_LEN:
        return None
    
    payload_len = packet_data[IDX_PAYLOAD_LEN]
    data_len = payload_len - MIN_PAYLOAD_LEN
    
    payload = b''
    if data_len > 0:
        start_idx = IDX_CMD + 1
        end_idx = start_idx + data_len
        payload = packet_data[start_idx:end_idx] if end_idx <= len(packet_data) else packet_data[start_idx:]
    
    return {
        'to': packet_data[IDX_TO_ADDR],
        'from': packet_data[IDX_FROM_ADDR], 
        'id': packet_data[IDX_PACKET_ID],
        'len': payload_len,
        'crc': packet_data[IDX_CRC],
        'cmd': packet_data[IDX_CMD],
        'payload': payload
    }

def format_packet(to_addr, from_addr, packet_id, cmd, payload=b''):
    """Construct packet with proper formatting and CRC."""
    if not (0 <= to_addr <= 255 and 0 <= from_addr <= 255 and 
            0 <= packet_id <= 255 and 0 <= cmd <= 255):
        return None
    
    payload_len = len(payload)
    if (payload_len + MIN_PAYLOAD_LEN) > 255:
        return None
    
    # Build header
    header = bytearray([to_addr, from_addr, packet_id, payload_len + MIN_PAYLOAD_LEN, 0])
    
    # Build full payload
    full_payload = bytearray([cmd]) + payload
    
    # Calculate and set CRC
    crc_data = header[:IDX_CRC] + full_payload
    header[IDX_CRC] = calcCRC8(crc_data, len(crc_data))
    
    return bytes(header + full_payload)

