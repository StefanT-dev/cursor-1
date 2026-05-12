#!/usr/bin/env python3
"""Simple Raspberry Pi water flow meter and tank level display.

The app counts pulses from a Hall-effect water flow sensor, converts those
pulses to litres, and shows current flow plus remaining tank volume in a
Tkinter window. It also has a simulation mode for setup/testing away from the
Pi.
"""

from __future__ import annotations

import argparse
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional, Protocol, Tuple

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - depends on OS image
    tk = None
    ttk = None


PulseCallback = Callable[[float], None]


class PulseSource(Protocol):
    """Source that calls a callback whenever the flow sensor emits a pulse."""

    def start(self, callback: PulseCallback) -> None:
        ...

    def stop(self) -> None:
        ...


class FlowStats:
    """Converts flow-meter pulses into volume and rolling flow measurements."""

    def __init__(
        self,
        pulses_per_litre: float,
        tank_litres: float,
        max_history_seconds: int = 3600,
    ) -> None:
        if pulses_per_litre <= 0:
            raise ValueError("pulses_per_litre must be greater than zero")
        if tank_litres < 0:
            raise ValueError("tank_litres cannot be negative")

        self.pulses_per_litre = pulses_per_litre
        self.tank_litres = tank_litres
        self.max_history_seconds = max_history_seconds
        self.total_pulses = 0
        self._buckets: Deque[Tuple[int, int]] = deque()

    def add_pulse(self, timestamp: Optional[float] = None) -> None:
        """Record one sensor pulse at a monotonic timestamp."""
        if timestamp is None:
            timestamp = time.monotonic()

        pulse_second = int(timestamp)
        self.total_pulses += 1

        if self._buckets and self._buckets[-1][0] == pulse_second:
            second, count = self._buckets[-1]
            self._buckets[-1] = (second, count + 1)
        else:
            self._buckets.append((pulse_second, 1))

        self._prune(timestamp)

    def set_calibration(self, pulses_per_litre: float) -> None:
        if pulses_per_litre <= 0:
            raise ValueError("pulses_per_litre must be greater than zero")
        self.pulses_per_litre = pulses_per_litre

    def set_tank_litres(self, tank_litres: float) -> None:
        if tank_litres < 0:
            raise ValueError("tank_litres cannot be negative")
        self.tank_litres = tank_litres

    def reset_used_volume(self) -> None:
        self.total_pulses = 0
        self._buckets.clear()

    def total_litres_used(self) -> float:
        return self.total_pulses / self.pulses_per_litre

    def tank_litres_remaining(self) -> float:
        return max(self.tank_litres - self.total_litres_used(), 0.0)

    def tank_percent_remaining(self) -> float:
        if self.tank_litres <= 0:
            return 0.0
        return (self.tank_litres_remaining() / self.tank_litres) * 100.0

    def litres_in_window(self, seconds: int, now: Optional[float] = None) -> float:
        if seconds <= 0:
            raise ValueError("seconds must be greater than zero")
        if now is None:
            now = time.monotonic()

        self._prune(now)
        cutoff = int(now - seconds)
        pulses = sum(count for second, count in self._buckets if second >= cutoff)
        return pulses / self.pulses_per_litre

    def litres_per_minute(self, sample_seconds: int = 10) -> float:
        return (self.litres_in_window(sample_seconds) / sample_seconds) * 60.0

    def _prune(self, now: float) -> None:
        cutoff = int(now - self.max_history_seconds)
        while self._buckets and self._buckets[0][0] < cutoff:
            self._buckets.popleft()


@dataclass
class GpioPulseSource:
    """Pulse source backed by Raspberry Pi GPIO edge detection."""

    pin: int
    edge: str = "falling"
    pull_up: bool = True
    bounce_ms: int = 5

    def __post_init__(self) -> None:
        self._gpio = None

    def start(self, callback: PulseCallback) -> None:
        try:
            import RPi.GPIO as GPIO
        except ImportError as exc:  # pragma: no cover - requires Pi hardware
            raise RuntimeError(
                "RPi.GPIO is not installed. Run this on Raspberry Pi OS, "
                "install RPi.GPIO, or start with --simulate."
            ) from exc

        GPIO.setmode(GPIO.BCM)
        pull = GPIO.PUD_UP if self.pull_up else GPIO.PUD_DOWN
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=pull)

        edges = {
            "falling": GPIO.FALLING,
            "rising": GPIO.RISING,
            "both": GPIO.BOTH,
        }
        GPIO.add_event_detect(
            self.pin,
            edges[self.edge],
            callback=lambda _channel: callback(time.monotonic()),
            bouncetime=self.bounce_ms,
        )
        self._gpio = GPIO

    def stop(self) -> None:
        if self._gpio is not None:  # pragma: no cover - requires Pi hardware
            self._gpio.cleanup(self.pin)
            self._gpio = None


@dataclass
class SimulatedPulseSource:
    """Generates fake pulses at a chosen flow rate for testing the GUI."""

    litres_per_minute: float
    pulses_per_litre: float

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, callback: PulseCallback) -> None:
        if self.litres_per_minute <= 0:
            return

        pulses_per_second = (self.litres_per_minute / 60.0) * self.pulses_per_litre
        interval = 1.0 / pulses_per_second

        def run() -> None:
            while not self._stop.wait(interval):
                callback(time.monotonic())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


class FlowMeterApp:
    """Tkinter dashboard for the flow meter."""

    def __init__(self, root: "tk.Tk", stats: FlowStats, pulse_source: PulseSource) -> None:
        if tk is None or ttk is None:
            raise RuntimeError("Tkinter is not installed on this Python system")

        self.root = root
        self.stats = stats
        self.pulse_source = pulse_source
        self.pulse_queue: "queue.SimpleQueue[float]" = queue.SimpleQueue()

        self.root.title("Raspberry Pi Water Flow Meter")
        self.root.geometry("620x430")

        self.flow_var = tk.StringVar()
        self.hour_rate_var = tk.StringVar()
        self.minute_volume_var = tk.StringVar()
        self.hour_volume_var = tk.StringVar()
        self.used_var = tk.StringVar()
        self.remaining_var = tk.StringVar()
        self.percent_var = tk.StringVar()
        self.pulses_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Starting...")

        self.tank_entry_var = tk.StringVar(value=f"{self.stats.tank_litres:g}")
        self.calibration_entry_var = tk.StringVar(value=f"{self.stats.pulses_per_litre:g}")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def run(self) -> None:
        try:
            self.pulse_source.start(lambda timestamp: self.pulse_queue.put(timestamp))
            self.status_var.set("Counting pulses")
        except Exception as exc:  # pragma: no cover - GUI path
            self.status_var.set(str(exc))

        self._update_ui()
        self.root.mainloop()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        title = ttk.Label(main, text="Water Flow Meter", font=("TkDefaultFont", 18, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        readings = ttk.LabelFrame(main, text="Live readings", padding=12)
        readings.grid(row=1, column=0, sticky="nsew", padx=(0, 12))

        self._add_reading(readings, "Flow now", self.flow_var, 0)
        self._add_reading(readings, "Current hourly rate", self.hour_rate_var, 1)
        self._add_reading(readings, "Used in last minute", self.minute_volume_var, 2)
        self._add_reading(readings, "Used in last hour", self.hour_volume_var, 3)
        self._add_reading(readings, "Total used", self.used_var, 4)
        self._add_reading(readings, "Pulse count", self.pulses_var, 5)

        tank_frame = ttk.LabelFrame(main, text="Tank", padding=12)
        tank_frame.grid(row=1, column=1, sticky="nsew")

        self.canvas = tk.Canvas(tank_frame, width=160, height=240, bg="white", highlightthickness=0)
        self.canvas.grid(row=0, column=0, columnspan=2, pady=(0, 10))

        ttk.Label(tank_frame, textvariable=self.remaining_var, font=("TkDefaultFont", 12, "bold")).grid(
            row=1, column=0, columnspan=2
        )
        ttk.Label(tank_frame, textvariable=self.percent_var).grid(row=2, column=0, columnspan=2)

        self.progress = ttk.Progressbar(tank_frame, orient="horizontal", length=160, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=2, pady=(8, 14), sticky="ew")

        ttk.Label(tank_frame, text="Tank size (L)").grid(row=4, column=0, sticky="w")
        ttk.Entry(tank_frame, textvariable=self.tank_entry_var, width=10).grid(row=4, column=1, sticky="e")
        ttk.Label(tank_frame, text="Pulses per L").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(tank_frame, textvariable=self.calibration_entry_var, width=10).grid(
            row=5, column=1, sticky="e", pady=(6, 0)
        )
        ttk.Button(tank_frame, text="Apply settings", command=self._apply_settings).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )
        ttk.Button(tank_frame, text="Reset used volume", command=self._reset_used_volume).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        status = ttk.Label(main, textvariable=self.status_var)
        status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0)
        readings.columnconfigure(1, weight=1)

    def _add_reading(self, parent: "ttk.Frame", label: str, variable: "tk.StringVar", row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Label(parent, textvariable=variable, font=("TkDefaultFont", 12, "bold")).grid(
            row=row, column=1, sticky="e", padx=(18, 0), pady=4
        )

    def _apply_settings(self) -> None:
        try:
            tank_litres = float(self.tank_entry_var.get())
            pulses_per_litre = float(self.calibration_entry_var.get())
            self.stats.set_tank_litres(tank_litres)
            self.stats.set_calibration(pulses_per_litre)
            self.status_var.set("Settings applied")
        except ValueError as exc:
            self.status_var.set(f"Invalid setting: {exc}")

    def _reset_used_volume(self) -> None:
        self.stats.reset_used_volume()
        self.status_var.set("Used volume reset")

    def _update_ui(self) -> None:
        self._drain_pulses()

        litres_per_minute = self.stats.litres_per_minute()
        minute_volume = self.stats.litres_in_window(60)
        hour_volume = self.stats.litres_in_window(3600)
        used = self.stats.total_litres_used()
        remaining = self.stats.tank_litres_remaining()
        percent = self.stats.tank_percent_remaining()

        self.flow_var.set(f"{litres_per_minute:.2f} L/min")
        self.hour_rate_var.set(f"{litres_per_minute * 60.0:.1f} L/hour")
        self.minute_volume_var.set(f"{minute_volume:.2f} L")
        self.hour_volume_var.set(f"{hour_volume:.2f} L")
        self.used_var.set(f"{used:.2f} L")
        self.remaining_var.set(f"{remaining:.2f} L left of {self.stats.tank_litres:.2f} L")
        self.percent_var.set(f"{percent:.0f}% remaining")
        self.pulses_var.set(str(self.stats.total_pulses))
        self.progress["value"] = percent
        self._draw_tank(percent)

        self.root.after(1000, self._update_ui)

    def _drain_pulses(self) -> None:
        while True:
            try:
                self.stats.add_pulse(self.pulse_queue.get_nowait())
            except queue.Empty:
                return

    def _draw_tank(self, percent: float) -> None:
        self.canvas.delete("all")
        x1, y1, x2, y2 = 42, 18, 118, 220
        fill_height = (y2 - y1) * max(min(percent, 100.0), 0.0) / 100.0
        fill_top = y2 - fill_height
        colour = "#2ecc71" if percent > 35 else "#f1c40f" if percent > 15 else "#e74c3c"

        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#333333", width=3)
        self.canvas.create_rectangle(x1 + 3, fill_top, x2 - 3, y2 - 3, fill=colour, outline="")
        self.canvas.create_text(80, 120, text=f"{percent:.0f}%", font=("TkDefaultFont", 20, "bold"))

    def _close(self) -> None:
        self.pulse_source.stop()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Graphical Raspberry Pi water flow meter")
    parser.add_argument("--pin", type=int, default=17, help="BCM GPIO pin connected to the sensor signal wire")
    parser.add_argument("--tank-litres", type=float, default=100.0, help="Tank capacity in litres")
    parser.add_argument(
        "--pulses-per-litre",
        type=float,
        default=450.0,
        help=(
            "Sensor calibration. 450 is common for YF-S201-style sensors; "
            "check/calibrate your G3/4 sensor for best accuracy."
        ),
    )
    parser.add_argument("--edge", choices=("falling", "rising", "both"), default="falling")
    parser.add_argument("--pull-down", action="store_true", help="Use GPIO pull-down instead of pull-up")
    parser.add_argument("--bounce-ms", type=int, default=5, help="GPIO debounce time in milliseconds")
    parser.add_argument("--simulate", action="store_true", help="Run without GPIO using fake flow pulses")
    parser.add_argument("--sim-litres-per-minute", type=float, default=10.0, help="Fake flow rate for --simulate")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = FlowStats(pulses_per_litre=args.pulses_per_litre, tank_litres=args.tank_litres)

    if args.simulate:
        pulse_source: PulseSource = SimulatedPulseSource(args.sim_litres_per_minute, args.pulses_per_litre)
    else:
        pulse_source = GpioPulseSource(
            pin=args.pin,
            edge=args.edge,
            pull_up=not args.pull_down,
            bounce_ms=args.bounce_ms,
        )

    if tk is None:
        raise SystemExit("Tkinter is not installed. Install python3-tk or run on Raspberry Pi OS with desktop.")

    root = tk.Tk()
    app = FlowMeterApp(root, stats, pulse_source)
    app.run()


if __name__ == "__main__":
    main()
