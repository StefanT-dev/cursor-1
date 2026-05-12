# Raspberry Pi 4 Water Flow Meter Dashboard

Simple Python GUI for a 3/4" hall-effect water flow meter (1-60 L/min) on Raspberry Pi.

It shows:
- Live flow rate in **L/min** and **L/hour**
- Volume passed in the **last minute** and **last hour**
- **Total used liters**
- **Remaining tank liters** (for example, start with 100 L)
- A clear visual tank level bar

## 1) Wiring (typical sensor)

Most 3-wire flow sensors use:
- **Red** -> 5V
- **Black** -> GND
- **Yellow** -> Signal (pulse output)

Connect signal to Raspberry Pi GPIO (default in this app: **GPIO 17**, BCM numbering).

Recommended: use a pull-up resistor/level-safe wiring if your exact sensor output needs it.

## 2) Run

```bash
python3 flow_meter_gui.py
```

If you run outside a Raspberry Pi (or GPIO fails), app starts in simulation mode so you can still test UI.

## 3) Settings in app

- **GPIO Pin (BCM)**: default `17`
- **Pulses/Liter**: default `450` (common value; calibrate your sensor)
- **Tank Capacity (L)**: full tank size
- **Tank Start (L)**: liters currently in tank at start (example: `100`)

Buttons:
- **Apply Settings**: apply calibration + GPIO pin
- **Reset Counters**: reset consumed liters to 0
- **Set Start = Capacity**: quick full tank setup

## 4) Calibration

Flow sensors vary by model and manufacturing tolerance.
If readings are not exact, adjust **Pulses/Liter**:

1. Pass a known amount of water (for example exactly 10 L).
2. Compare app total with real amount.
3. Increase/decrease Pulses/Liter until measured value matches reality.

## Notes

- For GPIO access on Raspberry Pi, run with permissions that can access GPIO (often `sudo`).
- This program assumes measured flow is water leaving the tank, so remaining tank liters decrease with usage.
