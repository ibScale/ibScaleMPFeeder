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
    Rotation starts a new file with an ever-increasing sequence number and deletes the
    oldest once there are more than `max_files`, so disk use is bounded to
    max_file_size * max_files (important on a small flash) while keeping a filename
    ordering (and dump_files() listing) that's always true chronological order, even
    across reboots.
    """

    def __init__(self, buffer_size=50, default_filepath='/flash/dmesg.log',
                 max_file_size=8192, max_files=3, flush_interval=1,
                 file_logging_enabled=False):
        # In-memory ring buffer as a plain list (MicroPython's deque isn't iterable,
        # which would break show()).
        self.buffer = []
        self.buffer_size = buffer_size
        self.log_count = 0   # monotonic total; never resets, used by console tail

        # File logging config. Worst-case disk use = max_file_size * max_files.
        self.max_size = max_file_size
        self.max_files = max_files if max_files >= 1 else 1
        self.flush_interval = flush_interval if flush_interval >= 1 else 1
        self.file_enabled = False
        self.log_dir = os.path.dirname(default_filepath)
        self.log_base = os.path.basename(default_filepath).split('.')[0]
        # Resume the newest existing rotated file (if any) instead of always restarting
        # at sequence 0, so a reboot doesn't jump backward into old file content or break
        # the chronological ordering dump_files() relies on.
        existing = self._discover_files()
        self._current_seq = existing[-1] if existing else 0
        self.filepath = self._indexed_path(self._current_seq)

        # Open-handle state
        self._fh = None
        self._bytes_in_file = 0
        self._flush_counter = 0

        # Uptime tracking immune to time.ticks_ms() wraparound: like Encoder.update()'s
        # counter-wraparound handling, each log() call folds the delta since the last
        # call into a running total that never resets, so displayed timestamps keep
        # climbing indefinitely instead of jumping backward when ticks_ms() wraps.
        self._last_ticks_ms = time.ticks_ms()
        self._uptime_ms = 0

        self.log("DMESG initialized.")
        if file_logging_enabled:
            self.configure_file_log(True)

    # --- File helpers -----------------------------------------------------

    def _indexed_path(self, seq):
        name = f"{self.log_base}_{seq:03d}.log"
        return f"{self.log_dir}/{name}" if self.log_dir else name

    def _discover_files(self):
        """Return existing rotated-file sequence numbers for log_base, sorted oldest-first.

        Sequence numbers are assigned once and never reused (see _rotate_file()), so this
        sort order always matches true chronological order - unlike a small modulo-cycled
        index, which starts reusing low numbers for the newest data once it wraps.
        """
        prefix = self.log_base + '_'
        try:
            entries = os.listdir(self.log_dir) if self.log_dir else os.listdir()
        except OSError:
            entries = []
        found = []
        for name in entries:
            if name.startswith(prefix) and name.endswith('.log'):
                try:
                    found.append(int(name[len(prefix):-4]))
                except ValueError:
                    pass
        found.sort()
        return found

    def _prune_old_files(self):
        """Delete the oldest rotated files once there are more than max_files."""
        existing = self._discover_files()
        excess = len(existing) - self.max_files
        if excess <= 0:
            return
        for seq in existing[:excess]:
            try:
                os.remove(self._indexed_path(seq))
            except OSError:
                pass

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
        """Start a new log file with the next (never-reused) sequence number, then prune
        old ones beyond max_files. Monotonic sequence numbers keep dump_files()'s sorted
        file listing in true chronological order indefinitely, including across reboots.
        """
        self._current_seq += 1
        self.filepath = self._indexed_path(self._current_seq)
        self._open_file(truncate=True)
        self._prune_old_files()

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

    def _uptime(self):
        """Return an ever-increasing uptime in ms, immune to time.ticks_ms() wraparound.

        ticks_ms() wraps at an implementation-defined period; reconstructing a running
        total from the delta since the last call (the same technique Encoder.update()
        uses for its hardware counter) means the displayed timestamp keeps climbing
        instead of jumping backward whenever ticks_ms() wraps.
        """
        now = time.ticks_ms()
        delta = time.ticks_diff(now, self._last_ticks_ms)
        if delta > 0:
            self._uptime_ms += delta
        self._last_ticks_ms = now
        return self._uptime_ms

    def uptime_ms(self):
        """Public wrap-safe uptime for other modules (e.g. the console's health and
        status lines) - raw time.ticks_ms() wraps back to 0 every ~12 days."""
        return self._uptime()

    def log(self, message):
        """Log message with an uptime timestamp to memory and optionally to file."""
        uptime_ms = self._uptime()
        secs, ms = divmod(uptime_ms, 1000)
        timestamp = f"[{secs:03d}.{ms:03d}]"
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
        # _discover_files() sorts by parsed sequence number (not raw filename string), so
        # ordering stays correct even once sequence numbers grow past 3 digits (where a
        # plain string sort of "_1000.log" vs "_999.log" would otherwise get it backwards).
        existing = self._discover_files()
        if not existing:
            print("(no rotated log files)")
            return
        for seq in existing:
            path = self._indexed_path(seq)
            print(f"--- {path} ---")
            try:
                with open(path) as f:
                    for line in f:
                        print(line, end='')
            except OSError as e:
                print(f"(error reading {path}: {e})")

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
            existing = self._discover_files()
            self._current_seq = existing[-1] if existing else 0
            self.filepath = self._indexed_path(self._current_seq)

        if self.file_enabled:
            return  # already on

        if not self._ensure_log_dir():
            return
        if self._open_file():
            self.file_enabled = True
            self.log(f"File logging enabled to {self.filepath}")
            self._save_timestamp()

    def _save_timestamp(self):
        """Append a wall-clock timestamp line (only meaningful if the RTC is set)."""
        if not self.file_enabled:
            return
        try:
            t = time.localtime(time.time())
            self._write_line(f"DMESG timestamp: {t[0]:04}-{t[1]:02}-{t[2]:02} {t[3]:02}:{t[4]:02}:{t[5]:02}")
        except Exception as e:
            print(f"Error writing timestamp to {self.filepath}: {e}")
