#!/usr/bin/env python3
"""Simple Raspberry Pi flow meter GUI.

Reads pulse output from a hall-effect water flow meter and displays:
- Current flow rate (L/min and L/hour)
- Volume that passed in the last minute and last hour
- Total used volume since reset
- Remaining tank volume from user-defined starting liters
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk

try:
    import RPi.GPIO as GPIO  # type: ignore

    GPIO_AVAILABLE = True
except ImportError:
    GPIO = None
    GPIO_AVAILABLE = False


class FlowTracker:
    """Tracks pulses in 1-second buckets for rolling volume windows."""

    def __init__(self, pulses_per_liter: float) -> None:
        self.pulses_per_liter = pulses_per_liter
        self.total_pulses = 0
        self.lock = threading.Lock()
        self.current_second = int(time.monotonic())
        self.second_buckets = deque([0] * 3600, maxlen=3600)

    def _roll_to_second(self, now_second: int) -> None:
        while self.current_second < now_second:
            self.second_buckets.append(0)
            self.current_second += 1

    def add_pulses(self, pulse_count: int = 1) -> None:
        now_second = int(time.monotonic())
        with self.lock:
            self._roll_to_second(now_second)
            self.second_buckets[-1] += pulse_count
            self.total_pulses += pulse_count

    def set_pulses_per_liter(self, pulses_per_liter: float) -> None:
        with self.lock:
            self.pulses_per_liter = pulses_per_liter

    def reset_total(self) -> None:
        with self.lock:
            self.total_pulses = 0
            self.current_second = int(time.monotonic())
            self.second_buckets = deque([0] * 3600, maxlen=3600)

    def metrics(self) -> dict[str, float]:
        now_second = int(time.monotonic())
        with self.lock:
            self._roll_to_second(now_second)
            pulses = list(self.second_buckets)
            ppl = self.pulses_per_liter
            pulses_last_5s = sum(pulses[-5:])
            pulses_last_min = sum(pulses[-60:])
            pulses_last_hour = sum(pulses)
            total_pulses = self.total_pulses

        # 5-second rolling average to keep the flow rate stable.
        flow_l_min = (pulses_last_5s * 60.0 / 5.0) / ppl
        flow_l_hour = flow_l_min * 60.0

        return {
            "flow_l_min": flow_l_min,
            "flow_l_hour": flow_l_hour,
            "last_min_liters": pulses_last_min / ppl,
            "last_hour_liters": pulses_last_hour / ppl,
            "total_liters": total_pulses / ppl,
        }


class FlowMeterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Water Flow Meter Dashboard")
        self.root.geometry("700x470")
        self.root.resizable(False, False)

        self.gpio_pin_var = tk.StringVar(value="17")
        self.pulses_per_liter_var = tk.StringVar(value="450")
        self.tank_capacity_var = tk.StringVar(value="100")
        self.tank_start_var = tk.StringVar(value="100")
        self.status_var = tk.StringVar(value="Initializing...")

        self.tracker = FlowTracker(pulses_per_liter=450.0)
        self.using_gpio = False

        self._build_ui()
        self._setup_gpio()
        self._update_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        config_frame = ttk.LabelFrame(main, text="Settings", padding=10)
        config_frame.pack(fill="x")

        ttk.Label(config_frame, text="GPIO Pin (BCM):").grid(row=0, column=0, sticky="w")
        ttk.Entry(config_frame, width=8, textvariable=self.gpio_pin_var).grid(row=0, column=1, sticky="w", padx=(5, 14))
        ttk.Label(config_frame, text="Pulses/Liter:").grid(row=0, column=2, sticky="w")
        ttk.Entry(config_frame, width=10, textvariable=self.pulses_per_liter_var).grid(row=0, column=3, sticky="w", padx=(5, 14))
        ttk.Label(config_frame, text="Tank Capacity (L):").grid(row=0, column=4, sticky="w")
        ttk.Entry(config_frame, width=10, textvariable=self.tank_capacity_var).grid(row=0, column=5, sticky="w", padx=(5, 14))
        ttk.Label(config_frame, text="Tank Start (L):").grid(row=0, column=6, sticky="w")
        ttk.Entry(config_frame, width=10, textvariable=self.tank_start_var).grid(row=0, column=7, sticky="w", padx=(5, 14))

        ttk.Button(config_frame, text="Apply Settings", command=self._apply_settings).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(config_frame, text="Reset Counters", command=self._reset_counters).grid(row=1, column=3, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(config_frame, text="Set Start = Capacity", command=self._set_start_to_capacity).grid(row=1, column=5, columnspan=3, sticky="w", pady=(10, 0))

        if not GPIO_AVAILABLE:
            ttk.Button(config_frame, text="Simulate +1L", command=self._simulate_one_liter).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        metrics_frame = ttk.LabelFrame(main, text="Live Metrics", padding=12)
        metrics_frame.pack(fill="x", pady=(12, 0))

        self.flow_min_label = ttk.Label(metrics_frame, text="0.00 L/min", font=("TkDefaultFont", 20, "bold"))
        self.flow_min_label.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.flow_hour_label = ttk.Label(metrics_frame, text="0.00 L/hour", font=("TkDefaultFont", 15))
        self.flow_hour_label.grid(row=1, column=0, padx=10, pady=4, sticky="w")

        self.last_min_label = ttk.Label(metrics_frame, text="Last minute: 0.00 L", font=("TkDefaultFont", 14))
        self.last_min_label.grid(row=0, column=1, padx=10, pady=8, sticky="w")
        self.last_hour_label = ttk.Label(metrics_frame, text="Last hour: 0.00 L", font=("TkDefaultFont", 14))
        self.last_hour_label.grid(row=1, column=1, padx=10, pady=4, sticky="w")
        self.total_label = ttk.Label(metrics_frame, text="Total used: 0.00 L", font=("TkDefaultFont", 14))
        self.total_label.grid(row=2, column=1, padx=10, pady=4, sticky="w")

        tank_frame = ttk.LabelFrame(main, text="Tank Status", padding=12)
        tank_frame.pack(fill="x", pady=(12, 0))

        self.remaining_label = ttk.Label(tank_frame, text="Remaining: 0.00 L", font=("TkDefaultFont", 18, "bold"))
        self.remaining_label.pack(anchor="w")
        self.percent_label = ttk.Label(tank_frame, text="0.0% full", font=("TkDefaultFont", 13))
        self.percent_label.pack(anchor="w", pady=(4, 8))

        self.tank_progress = ttk.Progressbar(tank_frame, orient="horizontal", mode="determinate", maximum=100)
        self.tank_progress.pack(fill="x")

        status_frame = ttk.Frame(main)
        status_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(status_frame, text="Status:").pack(side="left")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side="left", padx=(4, 0))

    def _setup_gpio(self) -> None:
        if not GPIO_AVAILABLE:
            self.status_var.set("GPIO module not found. Running in simulation mode.")
            return

        try:
            pin = int(self.gpio_pin_var.get().strip())
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            def on_pulse(channel: int) -> None:
                del channel
                self.tracker.add_pulses(1)

            GPIO.add_event_detect(pin, GPIO.FALLING, callback=on_pulse, bouncetime=2)
            self.using_gpio = True
            self.status_var.set(f"Listening on GPIO {pin}.")
        except Exception as exc:  # pragma: no cover - hardware/runtime path
            self.status_var.set(f"GPIO setup failed ({exc}). Using simulation mode.")
            self.using_gpio = False

    def _remove_gpio(self) -> None:
        if not GPIO_AVAILABLE or not self.using_gpio:
            return
        try:
            pin = int(self.gpio_pin_var.get().strip())
            GPIO.remove_event_detect(pin)
            GPIO.cleanup(pin)
        except Exception:
            pass
        self.using_gpio = False

    def _apply_settings(self) -> None:
        try:
            ppl = float(self.pulses_per_liter_var.get().strip())
            if ppl <= 0:
                raise ValueError
            self.tracker.set_pulses_per_liter(ppl)
        except ValueError:
            self.status_var.set("Invalid Pulses/Liter value.")
            return

        # Reconfigure GPIO pin if running on a Raspberry Pi.
        self._remove_gpio()
        self._setup_gpio()
        self.status_var.set(f"Settings applied (Pulses/Liter={self.tracker.pulses_per_liter:.2f}).")

    def _reset_counters(self) -> None:
        self.tracker.reset_total()
        self.status_var.set("Counters reset.")

    def _set_start_to_capacity(self) -> None:
        self.tank_start_var.set(self.tank_capacity_var.get())
        self.status_var.set("Tank start value set to capacity.")

    def _simulate_one_liter(self) -> None:
        if GPIO_AVAILABLE and self.using_gpio:
            return
        try:
            ppl = float(self.pulses_per_liter_var.get().strip())
            pulses = max(1, int(round(ppl)))
            self.tracker.add_pulses(pulses)
        except ValueError:
            self.status_var.set("Invalid Pulses/Liter for simulation.")

    def _safe_float(self, value: str, fallback: float = 0.0) -> float:
        try:
            return float(value.strip())
        except ValueError:
            return fallback

    def _update_ui(self) -> None:
        data = self.tracker.metrics()
        flow_l_min = data["flow_l_min"]
        flow_l_hour = data["flow_l_hour"]
        last_min_l = data["last_min_liters"]
        last_hour_l = data["last_hour_liters"]
        total_l = data["total_liters"]

        tank_capacity = max(0.0, self._safe_float(self.tank_capacity_var.get(), 0.0))
        tank_start = max(0.0, self._safe_float(self.tank_start_var.get(), tank_capacity))
        if tank_start > tank_capacity > 0:
            tank_start = tank_capacity

        remaining_l = max(0.0, tank_start - total_l)
        if tank_capacity > 0:
            percent = max(0.0, min(100.0, (remaining_l / tank_capacity) * 100.0))
        else:
            percent = 0.0

        self.flow_min_label.config(text=f"{flow_l_min:.2f} L/min")
        self.flow_hour_label.config(text=f"{flow_l_hour:.2f} L/hour")
        self.last_min_label.config(text=f"Last minute: {last_min_l:.2f} L")
        self.last_hour_label.config(text=f"Last hour: {last_hour_l:.2f} L")
        self.total_label.config(text=f"Total used: {total_l:.2f} L")
        self.remaining_label.config(text=f"Remaining: {remaining_l:.2f} L")
        self.percent_label.config(text=f"{percent:.1f}% full")
        self.tank_progress["value"] = percent

        self.root.after(500, self._update_ui)

    def _on_close(self) -> None:
        self._remove_gpio()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = FlowMeterApp(root)
    del app
    root.mainloop()


if __name__ == "__main__":
    main()
