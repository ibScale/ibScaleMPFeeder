# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# dmesg.py - Diagnostic Message logger

import time
import os
from collections import deque

class DmesgLogger:
    """Logger with fixed-size memory buffer and optional rotating file output."""
    
    def __init__(self, buffer_size=50, default_filepath='/flash/dmesg.log', max_file_size=102400, file_logging_enabled=False):
        self.buffer = deque((), buffer_size)
        self.filepath = default_filepath
        self.max_size = max_file_size
        self.file_index = 0
        self.file_enabled = file_logging_enabled
        self.log_dir = os.path.dirname(self.filepath)
        self.log_base = os.path.basename(self.filepath).split('.')[0]

        self.log("DMESG initialized.")
        if self.file_enabled:
            self.log(f"File logging enabled to {self.filepath}")
            self._ensure_log_dir()

    def _ensure_log_dir(self):
        """Create log directory if needed."""
        if self.log_dir and not os.path.exists(self.log_dir):
            try:
                os.makedirs(self.log_dir)
                self.log(f"Created log directory: {self.log_dir}")
            except OSError as e:
                self.file_enabled = False
                print(f"Error creating log directory {self.log_dir}: {e}. File logging disabled.")

    def log(self, message):
        """Log message with timestamp to memory and optionally to file."""
        uptime_ms = time.ticks_ms()
        timestamp = f"[{uptime_ms // 1000:03d}.{uptime_ms % 1000:03d}]"
        full_message = f"{timestamp} {message}"
        
        self.buffer.append(full_message)
        
        if self.file_enabled:
            try:
                # Check file size and rotate if needed
                try:
                    file_size = os.stat(self.filepath)[6]
                except OSError:
                    file_size = 0
                
                if file_size > self.max_size:
                    self.file_index += 1
                    base = self.log_base.split('_')[0] if '_' in self.log_base else self.log_base
                    self.filepath = f'{self.log_dir}/{base}_{self.file_index:03d}.log'
                    self.log(f"Log rotated to {self.filepath}")
                
                with open(self.filepath, 'a') as f:
                    f.write(full_message + '\n')
                    
            except OSError as e:
                print(f"Error writing to log {self.filepath}: {e}")
        
        print(full_message)

    def clear(self):
        """Clear memory buffer."""
        self.buffer.clear()
        self.log("Memory log cleared.")

    def show(self):
        """Display all memory buffer entries."""
        print("--- DMESG Buffer ---")
        for entry in self.buffer:
            print(entry)
        print("--------------------")

    def configure_file_log(self, enable, filepath=None):
        """Enable/disable file logging with optional new path."""
        if not enable:
            if self.file_enabled:
                self.log("File logging disabled.")
            self.file_enabled = False
            return
        
        if filepath:
            self.filepath = filepath
            self.log_dir = os.path.dirname(filepath)
            self.log_base = os.path.basename(filepath).split('.')[0]
            self.file_index = 0
        
        self._ensure_log_dir()
        
        if not self.file_enabled:
            self.log(f"File logging enabled to {self.filepath}")
            self.file_enabled = True
            self._save_timestamp()

    def _save_timestamp(self, offset=0):
        """Append timestamp to current log file."""
        if not self.file_enabled:
            return
        
        try:
            current_time = time.localtime(time.time() + offset * 3600)
            timestamp = f"DMESG timestamp: {current_time[0]:04}-{current_time[1]:02}-{current_time[2]:02} {current_time[3]:02}:{current_time[4]:02}:{current_time[5]:02}\n"
            with open(self.filepath, 'a') as f:
                f.write(timestamp)
        except OSError as e:
            print(f"Error writing timestamp to {self.filepath}: {e}")

    def save_buffer_to_file(self, filepath, offset=0):
        """Save entire memory buffer to specified file."""
        try:
            target_dir = os.path.dirname(filepath)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            with open(filepath, 'w') as f:
                f.write("--- DMESG Buffer Dump ---\n")
                for entry in self.buffer:
                    f.write(entry + '\n')
                
                current_time = time.localtime(time.time() + offset * 3600)
                timestamp = f"DMESG saved: {current_time[0]:04}-{current_time[1]:02}-{current_time[2]:02} {current_time[3]:02}:{current_time[4]:02}:{current_time[5]:02}\n"
                f.write(timestamp)
                f.write("-------------------------\n")
            
            print(f"DMESG buffer saved to {filepath}")
        except OSError as e:
            print(f"Error saving buffer to {filepath}: {e}")
