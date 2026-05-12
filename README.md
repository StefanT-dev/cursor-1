# Raspberry Pi 4 Water Flow + Tank Monitor

Simple Python app for a **G3/4 flow sensor (1-60 L/min)** on Raspberry Pi.

It shows, in a live dashboard:
- Current flow in **L/min**
- Current flow in **L/hr**
- Volume passed in the **last minute**
- Volume passed in the **last hour**
- **Total** volume passed
- **Tank liters remaining** (example: start at 100 L)

## 1) Wiring (typical 3-wire flow sensor)

Most sensors have:
- **Red** -> 5V
- **Black** -> GND
- **Yellow** (pulse output) -> Raspberry Pi GPIO input

Default GPIO in this program is **BCM 17** (physical pin 11).

> Note: Some flow sensor outputs are 5V pulses. Raspberry Pi GPIO is 3.3V only.  
> Use a voltage divider or logic-level shifter if needed.

## 2) Run on Raspberry Pi

```bash
python3 water_tank_monitor.py --gpio-pin 17 --tank-liters 100
```

This starts with tank at 100 L and subtracts measured outflow from it.

## 3) If your sensor calibration differs

Default calibration is:
- `450 pulses/liter` (common for many G3/4 1-60 L/min models)

If your sensor says something else, set:

```bash
python3 water_tank_monitor.py --pulses-per-liter 450 --tank-liters 100
```

## 4) Test on any computer (no GPIO hardware)

```bash
python3 water_tank_monitor.py --simulate --tank-liters 100
```

In simulate mode, you get a slider to change fake flow and see dashboard behavior.

## 5) Useful options

```bash
python3 water_tank_monitor.py --help
```

Options:
- `--gpio-pin` (default `17`)
- `--pulses-per-liter` (default `450`)
- `--tank-liters` (default `100`)
- `--sensor-max-l-min` (default `60`)
- `--simulate`
