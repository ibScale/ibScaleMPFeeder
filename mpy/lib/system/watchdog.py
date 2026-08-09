# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# watchdog.py - Optional hardware watchdog (STM32 IWDG).
#
# Opt-in per boot via SYSTEM.WATCHDOG_S (seconds; 0 = never started). start() takes ms
# (the native machine.WDT unit); the caller converts. The STM32 IWDG cannot be stopped
# once started and is capped near ~32s, so feed() must be called from every
# blocking loop (the main loop, the servo RT burst, the console, and the dev tools).
# feed() is a cheap no-op until start() actually arms it, so feed points are harmless
# when the watchdog is disabled.

import machine

_wdt = None


def start(timeout_ms):
    """Arm the watchdog if timeout_ms > 0 (idempotent). Returns True if armed."""
    global _wdt
    if _wdt is None and timeout_ms and timeout_ms > 0:
        try:
            _wdt = machine.WDT(timeout=timeout_ms)
        except Exception:
            _wdt = None
    return _wdt is not None


def feed():
    if _wdt is not None:
        _wdt.feed()
