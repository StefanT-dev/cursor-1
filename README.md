# Raspberry Pi 4 — Water Flow Meter

A simple graphical program for Raspberry Pi 4 that reads a **G3/4" Hall-effect water flow sensor** (1–60 L/min, e.g. YF-S201) and displays:

- **Flow rate** in L/min and L/hr
- **Total volume** used
- **Tank level** — set your tank size (e.g. 100 L) and watch the remaining amount drop in real time with a visual tank gauge

---

## Hardware Wiring

```
Flow sensor          Raspberry Pi 4
──────────           ──────────────
RED   (VCC)   ───►   5 V   (pin 2 or 4)
BLACK (GND)   ───►   GND   (pin 6)
YELLOW (SIG)  ───►   GPIO 17 (pin 11)
```

> You can use a different GPIO pin — pass `--pin <N>` when you run the program.

## Software Setup

```bash
# 1. Make sure Python 3 and tkinter are installed (both are default on Raspberry Pi OS)
sudo apt update
sudo apt install -y python3-tk

# 2. Install the GPIO library (usually pre-installed)
pip3 install RPi.GPIO
```

## Usage

### On the Raspberry Pi (real sensor)

```bash
python3 flow_meter.py                # 100 L tank by default
python3 flow_meter.py --tank 200     # 200 L tank
python3 flow_meter.py --pin 27       # sensor on GPIO 27
```

### Demo / simulation mode (no Pi needed)

```bash
python3 flow_meter.py --simulate
```

This generates fake pulses so you can test the GUI on any computer.

## What You See

| Element | Description |
|---------|-------------|
| **Flow Rate** | Current flow in L/min and L/hr |
| **Total Used** | Cumulative liters since last reset |
| **Tank Gauge** | Visual bar showing how full the tank is, with percentage |
| **Warnings** | Yellow when tank is below 25 %, red when below 10 % |

### Buttons

- **Reset Total** — zeroes the "Total Used" counter
- **Refill Tank** — resets the tank to full capacity
- **Set Tank Size** — change the tank capacity on the fly

## Calibration

The default calibration factor is **5.5 pulses/s per L/min** (typical for YF-S201).  
If your sensor has a different factor, edit the `CALIBRATION_FACTOR` constant at the top of `flow_meter.py`.

Most G3/4" sensors ship with a datasheet stating the formula:

```
Frequency (Hz) = CALIBRATION_FACTOR × Flow rate (L/min)
```

Adjust the constant to match your sensor.
