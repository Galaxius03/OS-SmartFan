# CSC1107 Operating Systems - Project 10
## GPIO Smart Fan Controller Driver (LED Variant)

This project implements a Raspberry Pi smart fan controller using an LED as the output device. It demonstrates Linux kernel/user-space communication through a custom character device driver, while also providing a Python API server and laptop dashboard for monitoring and manual control.

---

## Hardware Required

- Raspberry Pi 4
- Sense HAT for temperature readings
- LED
- 330 ohm resistor
- Breadboard and jumper wires

---

## Project Structure

```text
OS-SmartFan/
|-- project-root/
|   |-- led_driver.c          # Linux kernel module
|   |-- Makefile              # Compiles led_driver.c -> led_driver.ko
|   |-- led_control.c         # User-space C controller
|   `-- led_controller.sh     # Automated compile/load/run script
|
|-- Dashboard/                # Runs on laptop
|   |-- app.py                # Dashboard proxy server on port 8080
|   |-- templates/
|   |   `-- index.html
|   `-- static/
|       |-- styles.css
|       `-- app.js
|
|-- PiServers/                # Runs on Raspberry Pi
|   `-- led_server.py         # Flask REST API on port 5000
|
`-- Sensors/                  # Runs on Raspberry Pi
    |-- led.py                # Sense HAT sensor and LED control logic
    `-- led_controller.py     # Controller wrapper used by the API server
```

---

## Design Overview

The system is split into five layers:

1. `led_driver.c` creates `/dev/gpioled`, a Linux character device.
2. `led_control.c` opens `/dev/gpioled` and uses `write()` to send `ON` or `OFF`, then uses `read()` to get the kernel driver state.
3. `Sensors/led.py` reads the Sense HAT temperature, applies CPU heat correction, and writes the corrected value to `/tmp/sense_temp`.
4. `PiServers/led_server.py` exposes REST API endpoints for dashboard status and LED control.
5. `Dashboard/app.py` runs on the laptop and proxies browser requests to the Raspberry Pi API server.

Main data flow:

```text
Sense HAT
  -> Sensors/led.py
  -> /tmp/sense_temp
  -> project-root/led_control.c
  -> /dev/gpioled
  -> project-root/led_driver.c
  -> GPIO 24 LED
```

Dashboard/API flow:

```text
Browser
  -> Dashboard/app.py on laptop
  -> PiServers/led_server.py on Raspberry Pi
  -> Sensors/led.py
  -> /dev/gpioled
```

The LED turns on when the corrected temperature is at or above `29.0 C`. Humidity is intentionally excluded because the Sense HAT humidity sensor can be affected by Raspberry Pi CPU heat and may produce unreliable readings.

---

## Setup

### Raspberry Pi

Run these commands from `project-root/`:

```bash
cd project-root

# 1. Install dependencies
sudo apt install -y build-essential sense-hat
pip3 install flask --break-system-packages

# 2. Compile kernel module
make clean && make

# 3. Load kernel module
sudo insmod led_driver.ko

# 4. Fix device permissions
sudo chmod 666 /dev/gpioled

# 5. Make permissions permanent (run once)
echo 'KERNEL=="gpioled", MODE="0666"' | sudo tee /etc/udev/rules.d/99-gpioled.rules
sudo udevadm control --reload-rules
```

### Laptop Dashboard

Run these commands from the repository root:

```bash
cd Dashboard
pip3 install flask requests
```

---

## Running the Project

### Option A - Automated on Raspberry Pi

Run from `project-root/`:

```bash
cd project-root
chmod +x led_controller.sh
sudo ./led_controller.sh
```

This script compiles the kernel module, loads it, compiles the user-space C controller, demonstrates direct `/dev/gpioled` reads/writes, and starts the continuous controller.

### Option B - Manual

Terminal 1 on Pi - load the kernel module:

```bash
cd project-root
sudo insmod led_driver.ko
sudo chmod 666 /dev/gpioled
```

Terminal 2 on Pi - start the Flask API server:

```bash
python3 PiServers/led_server.py
```

Terminal 3 on Pi - run the C controller:

```bash
cd project-root
gcc -Wall -o led_control led_control.c
echo "30.5" > /tmp/sense_temp
sudo ./led_control
```

Terminal 4 on laptop - start the dashboard:

```bash
cd Dashboard
python app.py
```

Then open:

```text
http://localhost:8080
```

If the Pi hostname is not `raspberrypi.local`, set the Pi URL manually before running `Dashboard/app.py`:

```bash
export PI_URL=http://<pi-ip-address>:5000
python app.py
```

On Windows PowerShell:

```powershell
$env:PI_URL = "http://<pi-ip-address>:5000"
python app.py
```

---

## API Endpoints

The Raspberry Pi server exposes these endpoints:

```text
GET  /api/status
POST /api/led/on
POST /api/led/off
POST /api/led/auto
```

Example responses:

```json
{
  "led": {
    "is_on": true,
    "auto_mode": true
  },
  "environment": {
    "temperature": 30.2
  }
}
```

---

## Quick Test Commands

Run these on the Raspberry Pi:

```bash
# Verify kernel module loaded
lsmod | grep led_driver

# Check kernel log
dmesg | tail -20

# Manually test LED via device node
echo "ON" | sudo tee /dev/gpioled
echo "OFF" | sudo tee /dev/gpioled
sudo cat /dev/gpioled

# Test Flask API
curl http://localhost:5000/api/status
curl -X POST http://localhost:5000/api/led/on
curl -X POST http://localhost:5000/api/led/off
curl -X POST http://localhost:5000/api/led/auto \
  -H "Content-Type: application/json" \
  -d '{"active": true}'

# Unload kernel module
sudo rmmod led_driver
dmesg | tail -10
```

Expected `/dev/gpioled` output:

```text
LED:ON
LED:OFF
```

---

## Known Limitations

- The kernel module uses direct BCM2711 register access, so it is designed for Raspberry Pi 4.
- Hardware validation must be done on the Raspberry Pi because the kernel module and Sense HAT cannot be fully tested on a laptop.
- Temperature is corrected for CPU heat, but the exact correction may vary depending on the Pi case, airflow, and workload.
- Humidity is not used because the Sense HAT humidity reading can be unreliable near the CPU.

---

## Team

| Name | Student ID | Role |
|---|---:|---|
| Darrius John Chan Tiang Ser | 2500360 | Kernel module (`led_driver.c`, `Makefile`) |
| Hoon Chi Peng Shaun | 2500629 | User-space C and LED hardware (`led_control.c`) |
| Liris Goh | 2500011 | Sense HAT and Python server (`led.py`, `led_server.py`) |
| Vanessa Yee | 2502591 | Bash script and integration (`led_controller.sh`) |
| Zechary Wong | 2500819 | Report, slides, documentation |
