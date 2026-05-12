# Raspberry Pi water flow meter

Simple graphical Python program for a Raspberry Pi 4 and a Hall-effect water
flow meter such as a G3/4 inch 1-60 L/min sensor.

The app shows:

- current flow in litres/minute
- current hourly rate in litres/hour
- litres used in the last minute
- litres used in the last hour
- total litres used since reset
- remaining litres in a tank, for example `100 L`
- a visible tank graphic and progress bar

## Wiring

Most three-wire flow meters use:

| Sensor wire | Raspberry Pi connection |
| --- | --- |
| Red / VCC | 5V sensor supply |
| Black / GND | Pi GND |
| Yellow / signal | GPIO input, default BCM GPIO 17 |

Many sensors have an open-collector signal output, so this program uses the
Pi's internal pull-up by default. If your sensor output needs pull-down, start
the program with `--pull-down`.

> Check your exact meter datasheet before wiring. If the signal output is 5V,
> protect the Raspberry Pi GPIO with a level shifter or divider.

## Run on Raspberry Pi

```bash
python3 flow_meter_gui.py --pin 17 --tank-litres 100
```

If `RPi.GPIO` is missing:

```bash
sudo apt update
sudo apt install python3-rpi.gpio python3-tk
```

## Test without hardware

This opens the same graphical display and simulates 10 L/min:

```bash
python3 flow_meter_gui.py --simulate --tank-litres 100 --sim-litres-per-minute 10
```

## Calibration

The default calibration is `450` pulses per litre. Many flow sensors are
different, especially G3/4 models, so calibrate for best accuracy:

1. Put the outlet into a measured container.
2. Run exactly 10 L through the meter.
3. Note the pulse count shown by the app.
4. Divide pulse count by 10.
5. Use that number as `--pulses-per-litre`.

Example:

```bash
python3 flow_meter_gui.py --pin 17 --tank-litres 100 --pulses-per-litre 330
```

You can also change tank size and pulses per litre inside the app, then press
**Apply settings**. Press **Reset used volume** when the tank has been refilled.

## Run tests

```bash
python3 -m unittest
```
