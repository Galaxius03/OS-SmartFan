set -e
set -o pipefail

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

## Script Header
clear
echo "════════════════════════════════════════════════"
echo "   CSC1107 — Operating Systems, Project 10     "
echo "   GPIO Smart Fan Controller (LED Variant)     "
echo "════════════════════════════════════════════════"
echo ""
echo "  Device node  : /dev/gpioled"
echo "  GPIO pin     : BCM 24 (physical pin 18)"
echo "  Temp source  : /tmp/sense_temp (written by PiServers/led_server.py)"
echo "  Threshold    : 29.0 degrees C"
echo ""

# Compile header module first
echo "════════════════════════════════════════════════"
echo " STEP 1: Compiling kernel module"
echo " Command: make clean && make"
echo "════════════════════════════════════════════════"
make clean && make
echo ""
echo "[Step 1] Kernel module compiled successfully."
echo "[Step 1] Output: led_driver.ko"
echo ""

# Insert kernel module
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

# Compile user-space program
echo "════════════════════════════════════════════════"
echo " STEP 3: Compiling user-space C program"
echo " Command: gcc -Wall -o led_control led_control.c"
echo "════════════════════════════════════════════════"
gcc -Wall -o led_control led_control.c
echo "[Step 3] led_control compiled successfully."
echo ""

# Demostrate both write() and read() system calls
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

# Launch LED controller
echo "════════════════════════════════════════════════"
echo " STEP 5: Launching LED controller"
echo " Command: sudo ./led_control"
echo " (Press Ctrl-C to stop and unload the module)"
echo "════════════════════════════════════════════════"
echo ""
sudo ./led_control