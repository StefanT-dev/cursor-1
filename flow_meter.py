#!/usr/bin/env python3
"""
Raspberry Pi 4 — Water Flow Meter GUI
Sensor: G3/4" Hall-effect flow sensor (YF-S201 / similar), 1-60 L/min

Wiring:
  Sensor RED   → Pi 5V (pin 2 or 4)
  Sensor BLACK → Pi GND (pin 6)
  Sensor YELLOW (signal) → Pi GPIO 17 (pin 11)

Run:
  python3 flow_meter.py              # real mode (on the Pi)
  python3 flow_meter.py --simulate   # demo mode (no GPIO needed)
"""

import argparse
import math
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

# ---------------------------------------------------------------------------
# Sensor driver (real GPIO vs. simulation)
# ---------------------------------------------------------------------------

CALIBRATION_FACTOR = 5.5  # pulses per second per L/min (typical YF-S201)

pulse_count = 0
pulse_lock = threading.Lock()


def _gpio_callback(channel):
    global pulse_count
    with pulse_lock:
        pulse_count += 1


def setup_gpio(pin: int = 17):
    """Attach interrupt on the sensor signal pin."""
    import RPi.GPIO as GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(pin, GPIO.FALLING, callback=_gpio_callback)


class SimulatedSensor:
    """Generates fake pulses so the GUI can be tested on any PC."""

    def __init__(self):
        self._running = True
        self._rate_lpm = 5.0  # simulated L/min
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        global pulse_count
        while self._running:
            hz = self._rate_lpm * CALIBRATION_FACTOR
            if hz > 0:
                time.sleep(1.0 / hz)
                with pulse_lock:
                    pulse_count += 1
            else:
                time.sleep(0.1)

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

BG = "#1e1e2e"
FG = "#cdd6f4"
ACCENT = "#89b4fa"
WATER_COLOR = "#74c7ec"
WATER_DARK = "#1e66a0"
TANK_BG = "#313244"
RED = "#f38ba8"
YELLOW = "#f9e2af"
GREEN = "#a6e3a1"


class FlowMeterApp:
    SAMPLE_MS = 500  # read sensor every 500 ms

    def __init__(self, root: tk.Tk, tank_liters: float, simulate: bool):
        self.root = root
        self.tank_capacity = tank_liters
        self.tank_remaining = tank_liters
        self.total_liters = 0.0
        self.flow_rate_lpm = 0.0
        self.simulate = simulate

        self.root.title("Water Flow Meter")
        self.root.configure(bg=BG)
        self.root.geometry("520x700")
        self.root.resizable(False, False)

        self._build_ui()
        self._last_time = time.time()
        self._tick()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        # Title
        tk.Label(
            self.root, text="💧 Water Flow Meter", font=("Helvetica", 22, "bold"),
            bg=BG, fg=ACCENT,
        ).pack(pady=(14, 4))

        mode_text = "SIMULATION" if self.simulate else "LIVE SENSOR"
        tk.Label(
            self.root, text=f"[{mode_text}]", font=("Helvetica", 10),
            bg=BG, fg="#6c7086",
        ).pack()

        # --- Stats row ---
        stats = tk.Frame(self.root, bg=BG)
        stats.pack(pady=10, fill="x", padx=24)

        self.lbl_rate = self._stat_box(stats, "Flow Rate", "0.0 L/min", 0)
        self.lbl_rate_hr = self._stat_box(stats, "Flow Rate", "0.0 L/hr", 1)
        self.lbl_total = self._stat_box(stats, "Total Used", "0.00 L", 2)

        # --- Tank canvas ---
        self.canvas_w = 220
        self.canvas_h = 320
        self.tank_canvas = tk.Canvas(
            self.root, width=self.canvas_w, height=self.canvas_h,
            bg=BG, highlightthickness=0,
        )
        self.tank_canvas.pack(pady=6)

        # --- Tank label ---
        self.lbl_tank = tk.Label(
            self.root, text="", font=("Helvetica", 16, "bold"),
            bg=BG, fg=FG,
        )
        self.lbl_tank.pack()

        self.lbl_tank_pct = tk.Label(
            self.root, text="", font=("Helvetica", 12),
            bg=BG, fg="#6c7086",
        )
        self.lbl_tank_pct.pack()

        # --- Buttons ---
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(pady=14)

        self._make_btn(btn_frame, "Reset Total", self._reset_total, ACCENT).pack(side="left", padx=6)
        self._make_btn(btn_frame, "Refill Tank", self._refill_tank, GREEN).pack(side="left", padx=6)
        self._make_btn(btn_frame, "Set Tank Size", self._set_tank, YELLOW).pack(side="left", padx=6)

    def _stat_box(self, parent, title, default, col):
        frame = tk.Frame(parent, bg="#313244", padx=12, pady=8)
        frame.grid(row=0, column=col, padx=6, sticky="nsew")
        parent.columnconfigure(col, weight=1)
        tk.Label(frame, text=title, font=("Helvetica", 9), bg="#313244", fg="#6c7086").pack()
        lbl = tk.Label(frame, text=default, font=("Helvetica", 15, "bold"), bg="#313244", fg=FG)
        lbl.pack()
        return lbl

    def _make_btn(self, parent, text, cmd, color):
        return tk.Button(
            parent, text=text, command=cmd,
            font=("Helvetica", 11, "bold"), bg=color, fg="#1e1e2e",
            activebackground=color, activeforeground="#1e1e2e",
            relief="flat", padx=12, pady=4, cursor="hand2",
        )

    # ---- Tank drawing -----------------------------------------------------

    def _draw_tank(self):
        c = self.tank_canvas
        c.delete("all")
        w, h = self.canvas_w, self.canvas_h

        pad_x, pad_y_top, pad_y_bot = 40, 30, 20
        tw = w - 2 * pad_x
        th = h - pad_y_top - pad_y_bot

        tx = pad_x
        ty = pad_y_top

        # Tank outline (rounded rect)
        r = 14
        c.create_rectangle(tx, ty, tx + tw, ty + th, outline="#585b70", width=3, fill=TANK_BG)

        # Water level
        pct = max(0, min(1, self.tank_remaining / self.tank_capacity)) if self.tank_capacity > 0 else 0
        water_h = int(th * pct)
        wy = ty + th - water_h

        if water_h > 0:
            c.create_rectangle(tx + 2, wy, tx + tw - 2, ty + th - 2, outline="", fill=WATER_COLOR)
            # Subtle gradient line at water surface
            c.create_line(tx + 2, wy, tx + tw - 2, wy, fill=WATER_DARK, width=2)

        # Percentage markers
        for frac, label in [(0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "100%")]:
            ly = ty + th - int(th * frac)
            c.create_line(tx - 8, ly, tx, ly, fill="#585b70", width=1)
            c.create_text(tx - 12, ly, text=label, anchor="e", fill="#6c7086", font=("Helvetica", 8))

        # Big percentage text in the middle of the tank
        pct_display = pct * 100
        if pct_display > 50:
            txt_color = "#1e1e2e"
        else:
            txt_color = FG
        c.create_text(
            tx + tw // 2, ty + th // 2,
            text=f"{pct_display:.0f}%",
            font=("Helvetica", 28, "bold"), fill=txt_color,
        )

        # Color-coded warning
        if pct < 0.1:
            warn = "⚠ TANK NEARLY EMPTY"
            wc = RED
        elif pct < 0.25:
            warn = "Low"
            wc = YELLOW
        else:
            warn = ""
            wc = GREEN

        if warn:
            c.create_text(tx + tw // 2, ty - 12, text=warn, fill=wc, font=("Helvetica", 10, "bold"))

    # ---- Sensor reading / main loop ---------------------------------------

    def _tick(self):
        global pulse_count

        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        with pulse_lock:
            pulses = pulse_count
            pulse_count = 0

        if dt > 0:
            freq = pulses / dt
            self.flow_rate_lpm = freq / CALIBRATION_FACTOR
        else:
            self.flow_rate_lpm = 0.0

        liters_this_tick = self.flow_rate_lpm * (dt / 60.0)
        self.total_liters += liters_this_tick
        self.tank_remaining = max(0, self.tank_remaining - liters_this_tick)

        # Update labels
        self.lbl_rate.config(text=f"{self.flow_rate_lpm:.1f} L/min")
        self.lbl_rate_hr.config(text=f"{self.flow_rate_lpm * 60:.1f} L/hr")
        self.lbl_total.config(text=f"{self.total_liters:.2f} L")
        self.lbl_tank.config(text=f"{self.tank_remaining:.1f} L  remaining  /  {self.tank_capacity:.0f} L")
        pct = (self.tank_remaining / self.tank_capacity * 100) if self.tank_capacity > 0 else 0
        self.lbl_tank_pct.config(text=f"({pct:.1f}% full)")

        self._draw_tank()

        self.root.after(self.SAMPLE_MS, self._tick)

    # ---- Button actions ---------------------------------------------------

    def _reset_total(self):
        self.total_liters = 0.0

    def _refill_tank(self):
        self.tank_remaining = self.tank_capacity

    def _set_tank(self):
        val = simpledialog.askfloat(
            "Tank Size", "Enter tank capacity in liters:",
            initialvalue=self.tank_capacity, minvalue=1, maxvalue=100000,
            parent=self.root,
        )
        if val is not None:
            self.tank_capacity = val
            self.tank_remaining = val


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi Water Flow Meter")
    parser.add_argument("--simulate", action="store_true", help="Run with simulated sensor data (no GPIO)")
    parser.add_argument("--tank", type=float, default=100.0, help="Initial tank capacity in liters (default 100)")
    parser.add_argument("--pin", type=int, default=17, help="GPIO pin for sensor signal (BCM, default 17)")
    args = parser.parse_args()

    sim = None
    if args.simulate:
        sim = SimulatedSensor()
    else:
        try:
            setup_gpio(args.pin)
        except ImportError:
            print("RPi.GPIO not found. Run with --simulate to test without GPIO.")
            sys.exit(1)

    root = tk.Tk()
    app = FlowMeterApp(root, tank_liters=args.tank, simulate=args.simulate)

    def on_close():
        if sim:
            sim.stop()
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
