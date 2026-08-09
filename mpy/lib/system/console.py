# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# console.py - Serial console over the USB VCP, like a switch console port.
#
# Enter by pressing ESC three times within one second; the console then presents a
# text menu (calibrate / auto-tune / view sysconfig / etc). After 5 minutes with no
# input it drops back to monitoring (watching for ESC x3 again).
#
# NOTE: USB VCP is USB CDC, not a UART - the host's "baud rate" is cosmetic and the
# device receives bytes regardless, so there is no baud detection to do here.

import time
import asyncio
import os
import machine
import micropython
import pyb
from system.watchdog import feed as wdt_feed

_ESC = 0x1B
_ESC_WINDOW_MS = 1000     # three ESC within this window enters the console
_ESC_COUNT = 3
_INACTIVITY_MS = 300000   # 5 minutes of no input -> leave console
_HEALTH_INTERVAL_MS = 60000  # emit a health line every minute while unconnected
_MISSING = object()       # sentinel for "key not present" in the sysconfig editor


class SerialConsole:
    """Non-blocking ESC x3 detector + interactive text menu over pyb.USB_VCP()."""

    def __init__(self, app_passthrough, kbd_intr_resting=-1):
        self.app = app_passthrough
        self.dmesg = app_passthrough.get('DMESG')
        self.sysconfig = app_passthrough.get('SYSCONFIG')
        self.led = app_passthrough.get('LED')
        self.vcp = pyb.USB_VCP()
        self._esc_times = []
        # kbd_intr value to restore when the console exits: -1 when the app loop already
        # owns the VCP, or 3 when launched from boot so the REPL gets Ctrl+C back.
        self._resting_kbd = kbd_intr_resting
        self._last_health_ms = time.ticks_ms()

    # --- Entry detection (called each loop, non-blocking) -----------------

    def poll(self):
        """Drain pending VCP bytes; return True if ESC was seen 3x within the window.
        Also emits a periodic health line while unconnected. dmesg entries are not
        forwarded here: dmesg.log() already calls print(), which reaches the VCP
        directly since dupterm is never redirected away from it on this board."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_health_ms) >= _HEALTH_INTERVAL_MS:
            self._stream_health()
            self._last_health_ms = now
        if not self.vcp.any():
            return False
        data = self.vcp.read()
        if not data:
            return False
        now = time.ticks_ms()
        for b in data:
            if b == _ESC:
                self._esc_times.append(now)
        # Keep only ESCs still inside the detection window.
        self._esc_times = [t for t in self._esc_times if time.ticks_diff(now, t) <= _ESC_WINDOW_MS]
        if len(self._esc_times) >= _ESC_COUNT:
            self._esc_times = []
            return True
        return False

    def _stream_health(self):
        """Emit a one-line health summary to the VCP (called once per minute while unconnected)."""
        import gc
        # Wrap-safe uptime from dmesg (raw ticks_ms() wraps every ~12 days).
        up = self.dmesg.uptime_ms() if self.dmesg else time.ticks_ms()
        parts = [f"[{up // 1000:03d}.{up % 1000:03d}] HEALTH"]

        adc = self.app.get('ADC')
        if adc:
            try:
                vdc = adc.vmonvdc()
                vsys = adc.vmonsys()
                temp = adc.temp()
                if vdc is not None:
                    parts.append(f"VDC={vdc:.2f}V")
                if vsys is not None:
                    parts.append(f"VSYS={vsys:.2f}V")
                if temp is not None:
                    parts.append(f"T={temp:.0f}C")
            except Exception:
                pass

        try:
            used = gc.mem_alloc()
            free = gc.mem_free()
            total = used + free
            parts.append(f"RAM={used}/{total}({round(used / total * 100)}%)")
        except Exception:
            pass

        servo = self.app.get('SERVO')
        if servo:
            try:
                parts.append(f"servo={servo.result_name}")
                parts.append(f"pos={servo.get_current_position()}")
            except Exception:
                pass

        if self.sysconfig:
            parts.append(f"slot={self.sysconfig.get('SYSTEM.SLOTID', '?')}")

        self.vcp.write((' '.join(parts) + "\r\n").encode())

    # --- Low-level I/O ----------------------------------------------------

    def _write(self, s):
        self.vcp.write(s.encode() if isinstance(s, str) else s)

    async def _read_line(self, timeout_ms):
        """Read one line, echoing input. Returns the line, or None after timeout_ms of inactivity."""
        buf = b''
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            wdt_feed()  # menu can idle for minutes (> watchdog timeout); keep it fed
            if self.led:
                self.led.poll()  # keep the console-open blink animating while idle here
            if self.vcp.any():
                ch = self.vcp.read(1)
                if not ch:
                    continue
                deadline = time.ticks_add(time.ticks_ms(), timeout_ms)  # reset on activity
                c = ch[0]
                if c == 13 or c == 10:            # CR / LF
                    self._write("\r\n")
                    return buf.decode().strip()
                elif c == 127 or c == 8:          # DEL / Backspace
                    if buf:
                        buf = buf[:-1]
                        self._write("\b \b")
                elif 32 <= c < 127:               # printable
                    buf += ch
                    self._write(ch)
            else:
                await asyncio.sleep_ms(10)
        return None

    # --- Menu -------------------------------------------------------------

    def _banner(self):
        uuid = self.sysconfig.get('SYSTEM.UUID', '?') if self.sysconfig else '?'
        slot = self.sysconfig.get('SYSTEM.SLOTID', '?') if self.sysconfig else '?'
        self._write("\r\n\r\n=== ibScale MP Feeder Console ===\r\n")
        self._write(f"UUID: {uuid}  Slot: {slot}\r\n")

    def _menu(self):
        self._write(
            "\r\n"
            "  1) Run calibration\r\n"
            "  2) Run servo auto-tune\r\n"
            "  3) SysConfig\r\n"
            "  4) Show dmesg log\r\n"
            "  5) Button test\r\n"
            "  6) Status\r\n"
            "  R) Drop to REPL\r\n"
            "  B) Reboot (soft)\r\n"
            "  H) Hard reset\r\n"
            "  F) Factory reset (wipe /flash + reboot)\r\n"
            "  D) Enter DFU (firmware update)\r\n"
            "  0) Exit console\r\n"
            "feeder> "
        )

    async def run(self):
        """Run the interactive menu. Returns 'resume' or 'repl'. Assumes the app is paused."""
        micropython.kbd_intr(-1)   # console owns the VCP during the menu
        try:
            self._banner()
            while True:
                self._menu()
                line = await self._read_line(_INACTIVITY_MS)
                if line is None:
                    self._write("\r\n*** Idle timeout - returning to monitoring ***\r\n")
                    return 'resume'
                choice = line.lower()

                if choice == '1':
                    self._run_calibrate()
                elif choice == '2':
                    await self._run_profiler()
                elif choice == '3':
                    await self._sysconfig_menu()
                elif choice == '4':
                    self._show_dmesg()
                elif choice == '5':
                    await self._run_clicky()
                elif choice == '6':
                    self._show_status()
                elif choice == 'r':
                    self._write("Enabling USB mass storage for filesystem access...\r\n")
                    try:
                        pyb.usb_mode('VCP+MSC')
                        self._write("USB re-enumerating as VCP+MSC. Reconnect your serial terminal.\r\n")
                        self._write("The feeder volume (MPFEEDER) will mount on your host.\r\n")
                    except Exception as e:
                        self._write(f"MSC enable failed: {e}\r\n")
                    self._write("Dropping to REPL. Reset the board to return to normal operation.\r\n")
                    return 'repl'
                elif choice == 'b':
                    self._write("Rebooting...\r\n")
                    time.sleep_ms(100)
                    machine.soft_reset()
                elif choice == 'h':
                    self._write("Hard reset...\r\n")
                    time.sleep_ms(100)
                    machine.reset()
                elif choice == 'f':
                    await self._factory_reset()
                elif choice == 'd':
                    self._write("Entering DFU bootloader...\r\n")
                    time.sleep_ms(100)
                    machine.bootloader()
                elif choice in ('0', 'q', 'exit'):
                    self._write("Exiting console.\r\n")
                    return 'resume'
                elif choice == '':
                    pass
                else:
                    self._write("Unknown option.\r\n")
        except Exception as e:
            self._write(f"\r\nConsole error: {e}\r\n")
            return 'resume'
        finally:
            micropython.kbd_intr(self._resting_kbd)

    # --- Actions ----------------------------------------------------------

    def _run_calibrate(self):
        self._write("\r\n--- Calibration (motor will move, Ctrl+C aborts) ---\r\n")
        micropython.kbd_intr(3)   # re-enable Ctrl+C so the tool can be aborted
        try:
            from util.calibrate import run_calibrate
            run_calibrate(self.app)
        except (Exception, KeyboardInterrupt) as e:
            self._write(f"\r\nCalibration ended: {e}\r\n")
        finally:
            micropython.kbd_intr(-1)

    async def _run_profiler(self):
        self._write("\r\n--- Servo auto-tune (motor will move, Ctrl+C aborts) ---\r\n")
        micropython.kbd_intr(3)
        try:
            from util.profiler import run_performance_profiler
            await run_performance_profiler(self.app)
        except (Exception, KeyboardInterrupt) as e:
            self._write(f"\r\nAuto-tune ended: {e}\r\n")
        finally:
            micropython.kbd_intr(-1)

    async def _run_clicky(self):
        self._write("\r\n--- Button test (Ctrl+C to exit) ---\r\n")
        micropython.kbd_intr(3)
        try:
            from util.clicky import run_test
            await run_test(self.app)
        except (Exception, KeyboardInterrupt) as e:
            self._write(f"\r\nButton test ended: {e}\r\n")
        finally:
            micropython.kbd_intr(-1)

    def _show_status(self):
        from util.misc import mem_usage
        # Wrap-safe uptime from dmesg (raw ticks_ms() wraps every ~12 days).
        up = self.dmesg.uptime_ms() if self.dmesg else time.ticks_ms()
        self._write("\r\n--- Status ---\r\n")
        self._write(f"Uptime: {up // 1000}.{up % 1000:03d}s\r\n")
        mcu, avail, used, free = mem_usage()
        if avail:
            self._write(f"RAM: used {used}/{avail} ({round(used / avail * 100)}%), free {free}\r\n")
        adc = self.app.get('ADC')
        if adc:
            try:
                self._write(f"VDC: {adc.vmonvdc()}  VSYS: {adc.vmonsys()}  Temp: {adc.temp()}\r\n")
            except Exception as e:
                self._write(f"ADC read error: {e}\r\n")
        servo = self.app.get('SERVO')
        if servo:
            try:
                self._write(f"Servo: pos={servo.get_current_position()} cmd={servo.commanded_position} " +
                            f"last={servo.result_name} profile={servo.active_profile}\r\n")
            except Exception as e:
                self._write(f"Servo status error: {e}\r\n")

    async def _sysconfig_menu(self):
        """Simple registry-editor submenu: view / edit / save."""
        if not self.sysconfig:
            self._write("\r\nSYSCONFIG unavailable.\r\n")
            return
        while True:
            self._write(
                "\r\n--- SysConfig ---\r\n"
                "  1) View all\r\n"
                "  2) Edit a key\r\n"
                "  3) Save to flash\r\n"
                "  0) Back\r\n"
                "sysconfig> "
            )
            line = await self._read_line(_INACTIVITY_MS)
            if line is None:
                self._write("\r\n*** Idle timeout ***\r\n")
                return
            choice = line.lower()
            if choice == '1':
                self._write("\r\n")
                self.sysconfig.show()   # prints to stdout (the VCP)
            elif choice == '2':
                await self._edit_key()
            elif choice == '3':
                self.sysconfig.save()
                self._write("Saved.\r\n")
            elif choice in ('0', 'q', 'exit'):
                return
            elif choice == '':
                pass
            else:
                self._write("Unknown option.\r\n")

    async def _edit_key(self):
        self._write("\r\nKey (dot path, e.g. SERVO.CREEP), blank to cancel\r\nkey> ")
        key = await self._read_line(_INACTIVITY_MS)
        if not key:
            self._write("Cancelled.\r\n")
            return

        current = self.sysconfig.get(key, _MISSING)
        if isinstance(current, dict):
            self._write(f"'{key}' is a section, not a value - edit a key inside it.\r\n")
            return
        if current is _MISSING:
            self._write(f"'{key}' not found - enter a value to create it.\r\n")
            current = None
        else:
            self._write(f"Current: {key} = {repr(current)}\r\n")

        self._write("New value ('none' for null), blank to cancel\r\nvalue> ")
        raw = await self._read_line(_INACTIVITY_MS)
        if not raw:
            self._write("Cancelled.\r\n")
            return
        try:
            value = self._coerce(raw, current)
        except ValueError as e:
            self._write(f"Invalid value: {e}\r\n")
            return
        self.sysconfig.set(key, value)
        self._write(f"Set {key} = {repr(value)}  (use Save to persist)\r\n")

    def _coerce(self, raw, current):
        """Convert the entered string to match the existing value's type (infer if new)."""
        if raw.lower() in ('none', 'null'):
            return None
        if isinstance(current, bool):           # check before int (bool subclasses int)
            if raw.lower() in ('1', 'true', 'yes', 'on', 't', 'y'):
                return True
            if raw.lower() in ('0', 'false', 'no', 'off', 'f', 'n'):
                return False
            raise ValueError("expected true/false")
        if isinstance(current, int):
            return int(raw)
        if isinstance(current, float):
            return float(raw)
        if isinstance(current, str):
            return raw
        return self._infer(raw)                 # new / previously-null key

    def _infer(self, raw):
        low = raw.lower()
        if low == 'true':
            return True
        if low == 'false':
            return False
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    def _show_dmesg(self):
        self._write("\r\n")
        if self.dmesg and hasattr(self.dmesg, 'show'):
            self.dmesg.show()              # in-RAM buffer
            if hasattr(self.dmesg, 'dump_files'):
                self.dmesg.dump_files()    # plus any rotated file logs
        else:
            self._write("DMESG unavailable.\r\n")

    # --- Factory reset ----------------------------------------------------

    def _rmtree(self, path):
        """Recursively delete a directory and everything under it."""
        for entry in os.listdir(path):
            full = path + '/' + entry
            if os.stat(full)[0] & 0x4000:   # S_IFDIR
                self._rmtree(full)
            else:
                os.remove(full)
        os.rmdir(path)

    async def _factory_reset(self, root='/flash'):
        """Wipe everything on the filesystem (config, logs, overrides) and reset so the
        device boots from frozen defaults. The EEPROM-stored slot address is untouched."""
        self._write("\r\n*** FACTORY RESET ***\r\n")
        self._write(f"This erases ALL files on {root} (config, logs, dev overrides) and reboots\r\n" +
                    "to firmware defaults. The programmed slot address (EEPROM) is kept.\r\n")
        self._write("Type RESET to confirm (anything else cancels)\r\nconfirm> ")
        line = await self._read_line(_INACTIVITY_MS)
        if line != 'RESET':
            self._write("Cancelled.\r\n")
            return

        self._write(f"Wiping {root}...\r\n")
        try:
            entries = os.listdir(root)
        except OSError as e:
            self._write(f"Cannot list {root}: {e}\r\n")
            return
        for entry in entries:
            full = root + '/' + entry
            try:
                if os.stat(full)[0] & 0x4000:   # directory
                    self._rmtree(full)
                else:
                    os.remove(full)
                self._write(f"  removed {entry}\r\n")
            except OSError as e:
                self._write(f"  FAILED {entry}: {e}\r\n")

        self._write("Done. Rebooting to factory defaults...\r\n")
        time.sleep_ms(300)
        machine.reset()
