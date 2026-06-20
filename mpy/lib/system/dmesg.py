# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# dmesg.py - Diagnostic Message logger

import time
import os

class DmesgLogger:
    """Logger with a fixed-size in-memory buffer and optional rotating file output.

    File logging (off by default) keeps a single handle open and writes through it,
    flushing every `flush_interval` lines, so it avoids an open()/close() per message.
    Rotation cycles through a fixed set of `max_files` files (oldest is overwritten),
    so disk use is bounded to max_file_size * max_files - important on a small flash.
    """

    def __init__(self, buffer_size=50, default_filepath='/flash/dmesg.log',
                 max_file_size=8192, max_files=3, flush_interval=1,
                 file_logging_enabled=False):
        # In-memory ring buffer as a plain list (MicroPython's deque isn't iterable,
        # which would break show()/save_buffer_to_file()).
        self.buffer = []
        self.buffer_size = buffer_size
        self.log_count = 0   # monotonic total; never resets, used by console tail

        # File logging config. Worst-case disk use = max_file_size * max_files.
        self.max_size = max_file_size
        self.max_files = max_files if max_files >= 1 else 1
        self.flush_interval = flush_interval if flush_interval >= 1 else 1
        self.file_index = 0
        self.file_enabled = False
        self.log_dir = os.path.dirname(default_filepath)
        self.log_base = os.path.basename(default_filepath).split('.')[0]
        self.filepath = self._indexed_path(self.file_index)

        # Open-handle state
        self._fh = None
        self._bytes_in_file = 0
        self._flush_counter = 0

        self.log("DMESG initialized.")
        if file_logging_enabled:
            self.configure_file_log(True)

    # --- File helpers -----------------------------------------------------

    def _indexed_path(self, i):
        name = f"{self.log_base}_{i:03d}.log"
        return f"{self.log_dir}/{name}" if self.log_dir else name

    def _ensure_log_dir(self):
        """Create log directory if needed. Disables file logging on failure."""
        if self.log_dir and not os.path.exists(self.log_dir):
            try:
                os.makedirs(self.log_dir)
            except OSError as e:
                self.file_enabled = False
                print(f"Error creating log directory {self.log_dir}: {e}. File logging disabled.")
                return False
        return True

    def _open_file(self, truncate=False):
        """Open the current log file, keeping the handle. Returns True on success."""
        self._close_file()
        try:
            self._fh = open(self.filepath, 'w' if truncate else 'a')
            if truncate:
                self._bytes_in_file = 0
            else:
                try:
                    self._bytes_in_file = os.stat(self.filepath)[6]
                except OSError:
                    self._bytes_in_file = 0
            return True
        except OSError as e:
            print(f"Error opening log {self.filepath}: {e}. File logging disabled.")
            self._fh = None
            self.file_enabled = False
            return False

    def _close_file(self):
        if self._fh:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def _rotate_file(self):
        """Advance to the next file in the cycle, discarding the oldest."""
        self.file_index = (self.file_index + 1) % self.max_files
        self.filepath = self._indexed_path(self.file_index)
        self._open_file(truncate=True)

    def _write_line(self, text):
        """Write one line through the open handle (caller ensures file_enabled)."""
        if not self._fh and not self._open_file():
            return
        line = text + '\n'
        n = len(line)
        if self._bytes_in_file + n > self.max_size:
            self._rotate_file()
            if not self._fh:
                return
        try:
            self._fh.write(line)
            self._bytes_in_file += n
            self._flush_counter += 1
            if self._flush_counter >= self.flush_interval:
                self._flush_counter = 0
                self._fh.flush()
        except OSError as e:
            print(f"Error writing to log {self.filepath}: {e}")
            self._close_file()
            self.file_enabled = False

    # --- Logging ----------------------------------------------------------

    def log(self, message):
        """Log message with an uptime timestamp to memory and optionally to file."""
        uptime_ms = time.ticks_ms()
        timestamp = f"[{uptime_ms // 1000:03d}.{uptime_ms % 1000:03d}]"
        full_message = f"{timestamp} {message}"

        self.log_count += 1
        self.buffer.append(full_message)
        if len(self.buffer) > self.buffer_size:
            self.buffer.pop(0)

        if self.file_enabled:
            self._write_line(full_message)

        print(full_message)

    def dump_files(self):
        """Print the contents of all rotated log files (no-op if file logging is off)."""
        if self._fh:
            try:
                self._fh.flush()
            except OSError:
                pass
        try:
            entries = os.listdir(self.log_dir) if self.log_dir else os.listdir()
        except OSError:
            entries = []
        prefix = self.log_base + '_'
        found = False
        for name in sorted(entries):
            if name.startswith(prefix) and name.endswith('.log'):
                found = True
                path = f"{self.log_dir}/{name}" if self.log_dir else name
                print(f"--- {path} ---")
                try:
                    with open(path) as f:
                        for line in f:
                            print(line, end='')
                except OSError as e:
                    print(f"(error reading {path}: {e})")
        if not found:
            print("(no rotated log files)")

    def clear(self):
        """Clear memory buffer."""
        self.buffer = []
        self.log("Memory log cleared.")

    def show(self):
        """Display all memory buffer entries."""
        print("--- DMESG Buffer ---")
        for entry in self.buffer:
            print(entry)
        print("--------------------")

    # --- File logging control ---------------------------------------------

    def configure_file_log(self, enable, filepath=None):
        """Enable/disable file logging, optionally pointing at a new base path."""
        if not enable:
            if self.file_enabled:
                self.log("File logging disabled.")
            self.file_enabled = False
            self._close_file()
            return

        if filepath:
            self.log_dir = os.path.dirname(filepath)
            self.log_base = os.path.basename(filepath).split('.')[0]
            self.file_index = 0
            self.filepath = self._indexed_path(self.file_index)

        if self.file_enabled:
            return  # already on

        if not self._ensure_log_dir():
            return
        if self._open_file():
            self.file_enabled = True
            self.log(f"File logging enabled to {self.filepath}")
            self._save_timestamp()

    def close(self):
        """Flush and close the log file handle (call on shutdown)."""
        self._close_file()

    def _save_timestamp(self, offset=0):
        """Append a wall-clock timestamp line (only meaningful if the RTC is set)."""
        if not self.file_enabled:
            return
        try:
            t = time.localtime(time.time() + offset * 3600)
            self._write_line(f"DMESG timestamp: {t[0]:04}-{t[1]:02}-{t[2]:02} {t[3]:02}:{t[4]:02}:{t[5]:02}")
        except Exception as e:
            print(f"Error writing timestamp to {self.filepath}: {e}")

    def save_buffer_to_file(self, filepath, offset=0):
        """Save the entire in-memory buffer to a one-off file (separate from the log)."""
        try:
            target_dir = os.path.dirname(filepath)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir)

            with open(filepath, 'w') as f:
                f.write("--- DMESG Buffer Dump ---\n")
                for entry in self.buffer:
                    f.write(entry + '\n')

                t = time.localtime(time.time() + offset * 3600)
                f.write(f"DMESG saved: {t[0]:04}-{t[1]:02}-{t[2]:02} {t[3]:02}:{t[4]:02}:{t[5]:02}\n")
                f.write("-------------------------\n")

            print(f"DMESG buffer saved to {filepath}")
        except OSError as e:
            print(f"Error saving buffer to {filepath}: {e}")
