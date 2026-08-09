# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# gcutil.py - Shared gc.collect() wrapper.
#
# A full collection blocks for ~20-25ms (see APP.GC_INTERVAL_MS in defaults.py), which
# alone can push a single main-loop iteration over its APP.LOOP_INTERVAL_MS budget.
# app.py's own periodic collect() knows about itself, but gc.collect() can also be
# triggered mid-loop by something app.py doesn't call directly - e.g. sysconfig.save()
# runs one, and PROGRAM_FEEDER_FLOOR (photon.py) calls that synchronously from inside
# PHOTON.update() during a normal loop iteration. Without a shared record of "GC just
# ran", that shows up as a "Loop overrun" log even though it's just the known,
# already-accounted-for cost of GC, not a real scheduling problem. Every gc.collect()
# call in this codebase should go through collect() here instead of calling gc.collect()
# directly, so the main loop can always tell the difference.

import gc
import time

_last_ms = None


def collect():
    """Run a full collection and record when it completed."""
    global _last_ms
    gc.collect()
    _last_ms = time.ticks_ms()


def ran_recently(within_ms):
    """True if collect() completed within the last `within_ms` milliseconds."""
    return _last_ms is not None and time.ticks_diff(time.ticks_ms(), _last_ms) <= within_ms
