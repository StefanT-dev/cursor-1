#!/usr/bin/env python3
"""Simple Raspberry Pi water flow and tank monitor with GUI."""

from __future__ import annotations

import argparse
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Tuple

import tkinter as tk
from tkinter import ttk


@dataclass
class VolumeSample:
    timestamp: float
    liters: float


class GpioFlowMeter:
    """Count pulses from a hall-effect flow meter via Raspberry Pi GPIO."""

    def __init__(self, gpio_pin: int):
        import RPi.GPIO as GPIO  # Imported here so simulate mode works anywhere

        self.gpio = GPIO
        self.gpio_pin = gpio_pin
        self._pulse_count = 0
        self._lock = threading.Lock()

        self.gpio.setmode(self.gpio.BCM)
        self.gpio.setup(self.gpio_pin, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
        self.gpio.add_event_detect(
            self.gpio_pin,
            self.gpio.FALLING,
            callback=self._pulse_callback,
            bouncetime=2,
        )

    def _pulse_callback(self, channel: int) -> None:
        del channel  # callback signature required by RPi.GPIO
        with self._lock:
            self._pulse_count += 1

    def consume_pulses(self) -> int:
        with self._lock:
            pulses = self._pulse_count
            self._pulse_count = 0
            return pulses

    def cleanup(self) -> None:
        self.gpio.cleanup(self.gpio_pin)


class SimulatedFlowMeter:
    """Generate pulses in software so the app can be tested without hardware."""

    def __init__(self, pulses_per_liter: float, flow_l_min: float = 8.0):
        self.pulses_per_liter = pulses_per_liter
        self.flow_l_min = flow_l_min
        self._carry_pulses = 0.0
        self._last_time = time.time()

    def set_flow_l_min(self, flow_l_min: float) -> None:
        self.flow_l_min = max(0.0, flow_l_min)

    def consume_pulses(self) -> int:
        now = time.time()
        elapsed = max(now - self._last_time, 0.001)
        self._last_time = now

        pulses_float = (self.flow_l_min / 60.0) * self.pulses_per_liter * elapsed
        pulses_float += self._carry_pulses
        pulses_int = int(pulses_float)
        self._carry_pulses = pulses_float - pulses_int
        return pulses_int

    def cleanup(self) -> None:
        return


class TankTracker:
    def __init__(self, initial_liters: float):
        self.capacity_l = max(0.0, initial_liters)
        self.remaining_l = max(0.0, initial_liters)
        self.dispensed_since_refill_l = 0.0

    def add_outflow(self, liters: float) -> None:
        liters = max(0.0, liters)
        self.dispensed_since_refill_l += liters
        self.remaining_l = max(0.0, self.remaining_l - liters)

    def refill_to(self, liters: float) -> None:
        liters = max(0.0, liters)
        self.capacity_l = liters
        self.remaining_l = liters
        self.dispensed_since_refill_l = 0.0

    @property
    def percent_remaining(self) -> float:
        if self.capacity_l <= 0:
            return 0.0
        return (self.remaining_l / self.capacity_l) * 100.0


class WaterMonitorApp:
    def __init__(
        self,
        root: tk.Tk,
        flow_meter: GpioFlowMeter | SimulatedFlowMeter,
        pulses_per_liter: float,
        initial_tank_liters: float,
        sensor_max_l_min: float,
        simulate: bool,
    ):
        self.root = root
        self.flow_meter = flow_meter
        self.pulses_per_liter = pulses_per_liter
        self.sensor_max_l_min = sensor_max_l_min
        self.simulate = simulate

        self.tank = TankTracker(initial_tank_liters)
        self.total_volume_l = 0.0
        self.samples: Deque[VolumeSample] = deque()
        self.last_update = time.time()

        self._build_ui(initial_tank_liters)
        self._schedule_tick()

    def _build_ui(self, initial_tank_liters: float) -> None:
        self.root.title("Water Flow + Tank Monitor")
        self.root.geometry("560x520")
        self.root.configure(padx=12, pady=12)

        title = ttk.Label(
            self.root,
            text="Water Flow Meter Dashboard",
            font=("TkDefaultFont", 16, "bold"),
        )
        title.pack(pady=(0, 12))

        stats = ttk.Frame(self.root)
        stats.pack(fill="x")

        self.flow_min_var = tk.StringVar(value="0.00 L/min")
        self.flow_hr_var = tk.StringVar(value="0.00 L/hr")
        self.minute_vol_var = tk.StringVar(value="0.00 L")
        self.hour_vol_var = tk.StringVar(value="0.00 L")
        self.total_var = tk.StringVar(value="0.00 L")
        self.remaining_var = tk.StringVar(value=f"{initial_tank_liters:.2f} L")
        self.tank_pct_var = tk.StringVar(value="100.0%")
        self.dispensed_var = tk.StringVar(value="0.00 L")
        self.status_var = tk.StringVar(value="Sensor reading OK")

        self._add_stat_row(stats, "Current flow", self.flow_min_var)
        self._add_stat_row(stats, "Current flow (hour)", self.flow_hr_var)
        self._add_stat_row(stats, "Volume last minute", self.minute_vol_var)
        self._add_stat_row(stats, "Volume last hour", self.hour_vol_var)
        self._add_stat_row(stats, "Total volume passed", self.total_var)
        self._add_stat_row(stats, "Tank remaining", self.remaining_var)
        self._add_stat_row(stats, "Dispensed since refill", self.dispensed_var)

        flow_frame = ttk.LabelFrame(self.root, text="Flow bar (0 to sensor max)")
        flow_frame.pack(fill="x", pady=10)
        self.flow_progress = ttk.Progressbar(flow_frame, maximum=self.sensor_max_l_min)
        self.flow_progress.pack(fill="x", padx=10, pady=10)

        tank_frame = ttk.LabelFrame(self.root, text="Tank level")
        tank_frame.pack(fill="x", pady=10)

        self.tank_progress = ttk.Progressbar(tank_frame, maximum=100.0)
        self.tank_progress.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(tank_frame, textvariable=self.tank_pct_var).pack(pady=(0, 10))

        controls = ttk.LabelFrame(self.root, text="Tank controls")
        controls.pack(fill="x", pady=10)

        ttk.Label(controls, text="Reset tank liters:").grid(row=0, column=0, padx=8, pady=8)
        self.tank_entry = ttk.Entry(controls, width=12)
        self.tank_entry.insert(0, f"{initial_tank_liters:.0f}")
        self.tank_entry.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        ttk.Button(controls, text="Refill tank", command=self._refill_tank).grid(
            row=0, column=2, padx=8, pady=8, sticky="w"
        )

        if self.simulate and isinstance(self.flow_meter, SimulatedFlowMeter):
            sim_frame = ttk.LabelFrame(self.root, text="Simulation")
            sim_frame.pack(fill="x", pady=10)
            self.sim_scale = ttk.Scale(
                sim_frame,
                from_=0,
                to=self.sensor_max_l_min,
                orient="horizontal",
                command=self._on_sim_scale,
            )
            self.sim_scale.set(self.flow_meter.flow_l_min)
            self.sim_scale.pack(fill="x", padx=10, pady=(10, 0))
            self.sim_value_var = tk.StringVar(value=f"{self.flow_meter.flow_l_min:.1f} L/min")
            ttk.Label(sim_frame, textvariable=self.sim_value_var).pack(pady=(4, 10))

        status = ttk.Label(self.root, textvariable=self.status_var, foreground="#333")
        status.pack(anchor="w", pady=(8, 0))

    def _add_stat_row(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label + ":", width=24).pack(side="left")
        ttk.Label(row, textvariable=var, font=("TkDefaultFont", 11, "bold")).pack(side="left")

    def _on_sim_scale(self, value: str) -> None:
        if not isinstance(self.flow_meter, SimulatedFlowMeter):
            return
        flow = float(value)
        self.flow_meter.set_flow_l_min(flow)
        self.sim_value_var.set(f"{flow:.1f} L/min")

    def _refill_tank(self) -> None:
        try:
            liters = float(self.tank_entry.get().strip())
        except ValueError:
            self.status_var.set("Enter a valid tank number, e.g. 100")
            return

        if liters <= 0:
            self.status_var.set("Tank liters must be greater than zero")
            return

        self.tank.refill_to(liters)
        self.status_var.set(f"Tank reset to {liters:.1f} L")
        self._refresh_tank_ui()

    def _schedule_tick(self) -> None:
        self.root.after(1000, self._tick)

    def _tick(self) -> None:
        now = time.time()
        elapsed = max(now - self.last_update, 0.001)
        self.last_update = now

        pulses = self.flow_meter.consume_pulses()
        liters_interval = pulses / self.pulses_per_liter
        self.total_volume_l += liters_interval
        self.tank.add_outflow(liters_interval)
        self.samples.append(VolumeSample(timestamp=now, liters=liters_interval))
        self._prune_samples(now)

        flow_l_min = (liters_interval / elapsed) * 60.0
        flow_l_hr = flow_l_min * 60.0
        volume_1m = self._sum_window(now, 60.0)
        volume_1h = self._sum_window(now, 3600.0)

        self.flow_min_var.set(f"{flow_l_min:.2f} L/min")
        self.flow_hr_var.set(f"{flow_l_hr:.2f} L/hr")
        self.minute_vol_var.set(f"{volume_1m:.2f} L")
        self.hour_vol_var.set(f"{volume_1h:.2f} L")
        self.total_var.set(f"{self.total_volume_l:.2f} L")
        self.dispensed_var.set(f"{self.tank.dispensed_since_refill_l:.2f} L")

        self.flow_progress["value"] = min(max(flow_l_min, 0.0), self.sensor_max_l_min)
        self._refresh_tank_ui()

        if self.tank.remaining_l <= 0:
            self.status_var.set("Tank empty (or sensor volume exceeded entered tank liters)")
        elif pulses == 0:
            self.status_var.set("No flow pulses in this second")
        else:
            self.status_var.set("Sensor reading OK")

        self._schedule_tick()

    def _refresh_tank_ui(self) -> None:
        self.remaining_var.set(f"{self.tank.remaining_l:.2f} L")
        self.tank_pct_var.set(f"{self.tank.percent_remaining:.1f}%")
        self.tank_progress["value"] = self.tank.percent_remaining

    def _sum_window(self, now: float, window_seconds: float) -> float:
        return sum(sample.liters for sample in self.samples if now - sample.timestamp <= window_seconds)

    def _prune_samples(self, now: float) -> None:
        while self.samples and now - self.samples[0].timestamp > 3600.0:
            self.samples.popleft()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raspberry Pi flow meter + tank monitor")
    parser.add_argument("--gpio-pin", type=int, default=17, help="BCM GPIO pin (default: 17)")
    parser.add_argument(
        "--pulses-per-liter",
        type=float,
        default=450.0,
        help="Flow sensor calibration constant (default 450 pulses/L)",
    )
    parser.add_argument(
        "--tank-liters",
        type=float,
        default=100.0,
        help="Starting tank volume in liters (default: 100)",
    )
    parser.add_argument(
        "--sensor-max-l-min",
        type=float,
        default=60.0,
        help="Sensor max flow for progress bar (default: 60)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run without GPIO hardware using simulated flow",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.pulses_per_liter <= 0:
        raise SystemExit("pulses-per-liter must be > 0")
    if args.tank_liters <= 0:
        raise SystemExit("tank-liters must be > 0")

    if args.simulate:
        flow_meter: GpioFlowMeter | SimulatedFlowMeter = SimulatedFlowMeter(
            pulses_per_liter=args.pulses_per_liter
        )
    else:
        flow_meter = GpioFlowMeter(gpio_pin=args.gpio_pin)

    root = tk.Tk()
    app = WaterMonitorApp(
        root=root,
        flow_meter=flow_meter,
        pulses_per_liter=args.pulses_per_liter,
        initial_tank_liters=args.tank_liters,
        sensor_max_l_min=args.sensor_max_l_min,
        simulate=args.simulate,
    )
    del app

    def on_close() -> None:
        flow_meter.cleanup()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
