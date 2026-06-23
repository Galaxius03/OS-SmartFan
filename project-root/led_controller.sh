#!/bin/bash
#
# led_controller.sh — CSC1107 Operating Systems, Project 10
# GPIO Smart Fan Controller Driver (LED Variant)
#
# OVERVIEW
# ────────
# This Bash shell script automates the complete execution of the GPIO LED
# controller project. Users only need to launch this script — it handles
# kernel module compilation, insertion, user-space program compilation, and
# execution one by one, as required by the assignment brief.
#
# HOW IT SATISFIES THE ASSIGNMENT BRIEF
# ──────────────────────────────────────
# 1. Uses the make utility to compile the kernel module (led_driver.c)
# 2. Inserts the loadable kernel module into the Linux kernel (insmod)
# 3. Uses gcc to compile the user-space C program (led_control.c)
# 4. Launches the user-space program which:
#      - Sends write() system calls to /dev/gpioled ("ON"/"OFF" commands)
#      - Sends read() system calls to receive state from the kernel module
#      - Prints both messages to screen (user space output)
# 5. Displays kernel-space messages using dmesg after each key step
# 6. Cleanly removes the kernel module on exit (rmmod)
#
# USAGE
# ─────
#   chmod +x led_controller.sh
#   ./led_controller.sh
#
# NOTE: Run from the project root directory where led_driver.c is located.
#       For temperature-based auto control, start PiServers/led_server.py
#       in a separate terminal first (writes Sense HAT readings to
#       /tmp/sense_temp which led_control.c reads for threshold decisions).

# Exit immediately if any command fails
set -e
set -o pipefail

# ── Cleanup trap ──────────────────────────────────────────────────────────────
#
# This trap fires automatically when the script exits for any reason:
#   - User presses Ctrl-C
#   - Any command returns a non-zero exit code (due to set -e)
#   - Script reaches the end normally
#
# It ensures the kernel module is always cleanly removed from the kernel,
# preventing a stuck /dev/gpioled device or locked GPIO pin.

cleanup() {
    echo ""
    echo "════════════════════════════════════════════════"
    echo "  Shutting down — cleaning up resources..."
    echo "════════════════════════════════════════════════"

    if lsmod | grep -q "^led_driver"; then
        echo "[cleanup] Removing kernel module (sudo rmmod led_driver)..."
        sudo rmmod led_driver
        echo "[cleanup] led_driver removed from kernel."
    else
        echo "[cleanup] Module not loaded — nothing to remove."
    fi

    echo ""
    echo "[cleanup] Final kernel log (dmesg) — verify clean unload:"
    echo "────────────────────────────────────────────────"
    dmesg | tail -10
    echo "────────────────────────────────────────────────"
    echo "[cleanup] Done."
}

trap cleanup EXIT

# ── Script header ─────────────────────────────────────────────────────────────
clear
echo "════════════════════════════════════════════════"
echo "   CSC1107 — Operating Systems, Project 10     "
echo "   GPIO Smart Fan Controller (LED Variant)     "
echo "════════════════════════════════════════════════"
echo ""
echo "  Device node  : /dev/gpioled"
echo "  GPIO pin     : BCM 24 (physical pin 18)"
echo "  Temp source  : /tmp/sense_temp"
echo "  Threshold    : 29.0 degrees C"
echo ""

# ── Step 1: Compile the kernel module ─────────────────────────────────────────
echo "════════════════════════════════════════════════"
echo " STEP 1: Compiling kernel module"
echo " Command: make clean && make"
echo "════════════════════════════════════════════════"
make clean && make
echo ""
echo "[Step 1] Kernel module compiled successfully."
echo "[Step 1] Output: led_driver.ko"
echo ""

# ── Step 2: Insert the kernel module ──────────────────────────────────────────
echo "════════════════════════════════════════════════"
echo " STEP 2: Inserting kernel module into the kernel"
echo " Command: sudo insmod led_driver.ko"
echo "════════════════════════════════════════════════"

# Remove previous instance if already loaded to avoid conflicts
if lsmod | grep -q "^led_driver"; then
    echo "[Step 2] Previous instance found — removing first..."
    sudo rmmod led_driver
    echo "[Step 2] Previous instance removed."
fi

sudo insmod led_driver.ko

# Verify module loaded successfully
if lsmod | grep -q "^led_driver"; then
    echo "[Step 2] led_driver inserted into kernel successfully."
    echo "[Step 2] Device node /dev/gpioled is now available."
else
    echo "[Step 2] ERROR: Module failed to load. Check dmesg."
    exit 1
fi

# Fix permissions so user-space programs can access /dev/gpioled
sudo chmod 666 /dev/gpioled
echo "[Step 2] /dev/gpioled permissions set."
echo ""

# Display kernel log to show module init messages (printk output)
echo "[Step 2] Kernel log after insmod (dmesg):"
echo "────────────────────────────────────────────────"
dmesg | tail -15
echo "────────────────────────────────────────────────"
echo ""

# ── Step 3: Compile the user-space C program ──────────────────────────────────
echo "════════════════════════════════════════════════"
echo " STEP 3: Compiling user-space C program"
echo " Command: gcc -Wall -o led_control led_control.c"
echo "════════════════════════════════════════════════"
gcc -Wall -o led_control led_control.c
echo "[Step 3] led_control compiled successfully."
echo ""

# ── Step 4: Demonstrate write() and read() system calls ───────────────────────
#
# Before launching the continuous controller, demonstrate the write() and
# read() system calls directly from the bash script as required by the brief.
# This shows the kernel/user-space communication working.

echo "════════════════════════════════════════════════"
echo " STEP 4: Demonstrating write() and read() calls"
echo " Sending commands directly to /dev/gpioled"
echo "════════════════════════════════════════════════"

echo ""
echo "[Step 4] Sending write() — 'Hello from user space: ON'"
echo "ON" > /dev/gpioled
echo "[Step 4] write() sent. Kernel log:"
dmesg | tail -3

echo ""
echo "[Step 4] Sending read()  — reading state from kernel space:"
STATE=$(cat /dev/gpioled)
echo "[Step 4] Kernel replied: $STATE"
echo "[Step 4] Message successfully received from kernel space."

echo ""
echo "[Step 4] Sending write() — 'Hello from user space: OFF'"
echo "OFF" > /dev/gpioled
echo "[Step 4] write() sent. Kernel log:"
dmesg | tail -3

echo ""
echo "[Step 4] Sending read()  — reading state from kernel space:"
STATE=$(cat /dev/gpioled)
echo "[Step 4] Kernel replied: $STATE"
echo "[Step 4] Message successfully received from kernel space."
echo ""

# ── Step 5: Launch the LED controller ─────────────────────────────────────────
#
# led_control continuously reads temperature from /tmp/sense_temp,
# sends write() commands ("ON"/"OFF") to /dev/gpioled, and receives
# the current LED state back via read() — printing both to screen.

echo "════════════════════════════════════════════════"
echo " STEP 5: Launching LED controller"
echo " Command: sudo ./led_control"
echo " (Press Ctrl-C to stop and unload the module)"
echo "════════════════════════════════════════════════"
echo ""
sudo ./led_control
