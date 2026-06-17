/*
 * led_driver.c — CSC1107 Operating Systems, Project 10
 * GPIO LED Indicator — Linux Loadable Kernel Module (LKM)
 *
 * WHAT THIS MODULE DOES
 * ─────────────────────
 * Creates a character device at /dev/gpioled. User-space programs write "ON"
 * or "OFF" to control a physical LED, and read back the current LED state.
 *
 *   User space                   Kernel space              Hardware
 *   ─────────                    ────────────              ────────
 *   write(fd, "ON",  2)  ──►  dev_write() ──► gpio_set_value(pin, 1) ──► LED ON
 *   write(fd, "OFF", 3)  ──►  dev_write() ──► gpio_set_value(pin, 0) ──► LED OFF
 *   read (fd, buf,   8)  ──►  dev_read()  ──► returns "LED:ON\n" or "LED:OFF\n"
 *
 * SIMULATION MODE
 * ───────────────
 * On kernels >= 6.x the legacy gpio_request() API may return -EPROBE_DEFER
 * (-517) even for valid pins. If GPIO cannot be claimed, the module loads in
 * simulation mode: /dev/gpioled is fully functional for read/write, but no
 * physical pin is driven. This allows testing the character device logic
 * without hardware. gpio_available tracks which mode is active.
 *
 * HARDWARE SETUP (when GPIO is available)
 * ────────────────────────────────────────
 *   Raspberry Pi GPIO 24 (BCM)  ──[330 Ω]──  LED anode (+)
 *   Raspberry Pi GND            ────────────  LED cathode (-)
 *
 * USAGE
 * ─────
 *   make                        (compile — produces led_driver.ko)
 *   sudo insmod led_driver.ko   (load module into the kernel)
 *   dmesg | tail -20            (verify init messages)
 *   sudo rmmod led_driver       (unload and release all resources)
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/gpio.h>
#include <linux/uaccess.h>
#include <linux/string.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("CSC1107 Group — Project 10");
MODULE_DESCRIPTION("GPIO LED indicator driver: ON/OFF via /dev/gpioled, "
                   "controlled by Sense HAT temperature threshold");
MODULE_VERSION("1.0");

/* ── Configuration ───────────────────────────────────────────────────────── */
#define DEVICE_NAME  "gpioled"    /* Creates /dev/gpioled after device_create  */
#define CLASS_NAME   "gpio_led"   /* Sysfs class at /sys/class/gpio_led/       */
#define GPIO_LED_PIN  24          /* BCM GPIO 24 = physical header pin 18      */

/*
 * BCM (Broadcom) pin numbering is used — NOT physical pin numbers.
 * BCM 24 = physical pin 18 on the 40-pin header.
 * Do NOT change without updating hardware wiring on the Pi.
 */

/* ── Module-level state ──────────────────────────────────────────────────── */
static dev_t          dev_number;
static struct class  *led_class  = NULL;
static struct device *led_device = NULL;
static struct cdev    led_cdev;

/* Current LED state: 0 = off, 1 = on */
static int led_state = 0;

/*
 * gpio_available — set to 1 if gpio_request() succeeded at init time.
 * When 0, the module runs in simulation mode: /dev/gpioled works for
 * read/write but no physical GPIO pin is driven.
 */
static int gpio_available = 0;

/* ── Forward declarations ────────────────────────────────────────────────── */
static int     dev_open    (struct inode *inode, struct file *filp);
static int     dev_release (struct inode *inode, struct file *filp);
static ssize_t dev_read    (struct file *filp, char __user *buf,
                            size_t len, loff_t *offset);
static ssize_t dev_write   (struct file *filp, const char __user *buf,
                            size_t len, loff_t *offset);

/*
 * file_operations — maps system calls on /dev/gpioled to our handlers.
 *   open()    → dev_open()
 *   release() → dev_release()
 *   read()    → dev_read()
 *   write()   → dev_write()
 */
static const struct file_operations fops = {
    .owner   = THIS_MODULE,
    .open    = dev_open,
    .release = dev_release,
    .read    = dev_read,
    .write   = dev_write,
};

/* ═══════════════════════════════════════════════════════════════════════════
 * DEVICE OPERATION HANDLERS
 * ═══════════════════════════════════════════════════════════════════════════ */

/*
 * dev_open — called when user space opens /dev/gpioled.
 * No per-open resources needed; log the event to dmesg.
 */
static int dev_open(struct inode *inode, struct file *filp)
{
    printk(KERN_INFO "gpioled: device opened by user-space process\n");
    return 0;
}

/*
 * dev_release — called when user space closes the file descriptor.
 */
static int dev_release(struct inode *inode, struct file *filp)
{
    printk(KERN_INFO "gpioled: device closed by user-space process\n");
    return 0;
}

/*
 * dev_read — returns current LED state to user space.
 *
 * Returns "LED:ON\n" or "LED:OFF\n" on the first read per open().
 * Returns 0 (EOF) on subsequent reads so `cat /dev/gpioled` terminates.
 *
 * The *offset trick: we send the state string once, advance offset past
 * it, then return 0 on any further read() calls this open().
 */
static ssize_t dev_read(struct file *filp, char __user *buf,
                        size_t len, loff_t *offset)
{
    char response[16];
    int  response_len;

    /* EOF guard — already served a read this open() */
    if (*offset > 0)
        return 0;

    if (led_state)
        snprintf(response, sizeof(response), "LED:ON\n");
    else
        snprintf(response, sizeof(response), "LED:OFF\n");

    response_len = strlen(response);

    if (len < response_len) {
        printk(KERN_WARNING "gpioled: read() buffer too small "
               "(%zu bytes, need %d)\n", len, response_len);
        return -EINVAL;
    }

    /*
     * copy_to_user — copies kernel memory into user-space buffer safely.
     * Direct pointer dereference across the boundary is a security violation.
     */
    if (copy_to_user(buf, response, response_len)) {
        printk(KERN_ERR "gpioled: copy_to_user failed in dev_read\n");
        return -EFAULT;
    }

    *offset += response_len;
    printk(KERN_INFO "gpioled: state sent to user space → %s", response);
    return response_len;
}

/*
 * dev_write — receives LED command from user space and drives GPIO.
 *
 * Accepted commands:
 *   "ON"  → gpio_set_value(GPIO_LED_PIN, 1) → LED on  (if GPIO available)
 *   "OFF" → gpio_set_value(GPIO_LED_PIN, 0) → LED off (if GPIO available)
 *
 * In simulation mode (gpio_available == 0), the state is updated in memory
 * but no physical pin is driven — useful for testing the driver logic.
 *
 * strncmp is used so callers may send "ON\n" without failing the match.
 * Unknown commands are rejected with -EINVAL.
 */
static ssize_t dev_write(struct file *filp, const char __user *buf,
                         size_t len, loff_t *offset)
{
    char   command[8];
    size_t copy_len = min(len, sizeof(command) - 1);

    /*
     * copy_from_user — copies user-space buffer into kernel memory safely.
     * Never dereference a user-space pointer directly from kernel code.
     */
    if (copy_from_user(command, buf, copy_len)) {
        printk(KERN_ERR "gpioled: copy_from_user failed in dev_write\n");
        return -EFAULT;
    }

    command[copy_len] = '\0';   /* null-terminate for safe string comparison */

    if (strncmp(command, "ON", 2) == 0) {
        if (gpio_available)
            gpio_set_value(GPIO_LED_PIN, 1);    /* drive pin HIGH → LED on  */
        led_state = 1;
        printk(KERN_INFO "gpioled: command 'ON'  received — GPIO %d %s\n",
               GPIO_LED_PIN, gpio_available ? "HIGH" : "(simulated)");

    } else if (strncmp(command, "OFF", 3) == 0) {
        if (gpio_available)
            gpio_set_value(GPIO_LED_PIN, 0);    /* drive pin LOW  → LED off */
        led_state = 0;
        printk(KERN_INFO "gpioled: command 'OFF' received — GPIO %d %s\n",
               GPIO_LED_PIN, gpio_available ? "LOW"  : "(simulated)");

    } else {
        printk(KERN_WARNING "gpioled: unknown command '%s' "
               "(expected 'ON' or 'OFF')\n", command);
        return -EINVAL;
    }

    /* Return full len — we consumed all bytes the caller gave us */
    return len;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * MODULE INIT AND EXIT
 * ═══════════════════════════════════════════════════════════════════════════ */

/*
 * led_driver_init — runs on `sudo insmod led_driver.ko`.
 *
 * Steps 1–4 set up the character device and are fatal if they fail.
 * Steps 5–6 (GPIO) are non-fatal: if gpio_request() fails (e.g. kernel
 * returns -EPROBE_DEFER on newer kernels), the module continues in
 * simulation mode and gpio_available stays 0.
 *
 * Goto labels unwind only the steps that already succeeded, in reverse.
 */
static int __init led_driver_init(void)
{
    int ret;

    printk(KERN_INFO "gpioled: ── loading module ──────────────────────────\n");

    /* Step 1: Allocate major + minor device number dynamically */
    ret = alloc_chrdev_region(&dev_number, 0, 1, DEVICE_NAME);
    if (ret < 0) {
        printk(KERN_ERR "gpioled: Step 1 FAILED — alloc_chrdev_region (%d)\n",
               ret);
        return ret;
    }
    printk(KERN_INFO "gpioled: Step 1 OK — major number %d allocated\n",
           MAJOR(dev_number));

    /* Step 2: Link file_operations to the character device struct */
    cdev_init(&led_cdev, &fops);
    led_cdev.owner = THIS_MODULE;
    ret = cdev_add(&led_cdev, dev_number, 1);
    if (ret < 0) {
        printk(KERN_ERR "gpioled: Step 2 FAILED — cdev_add (%d)\n", ret);
        goto err_unreg;
    }
    printk(KERN_INFO "gpioled: Step 2 OK — character device registered\n");

    /* Step 3: Create device class at /sys/class/gpio_led/
     *
     * NOTE: class_create() signature changed in kernel 6.3 — THIS_MODULE
     * argument was removed. This file already uses the new single-argument
     * form. If you see a compile error here on an older kernel, add
     * THIS_MODULE as the first argument.
     */
    led_class = class_create(CLASS_NAME);
    if (IS_ERR(led_class)) {
        ret = PTR_ERR(led_class);
        printk(KERN_ERR "gpioled: Step 3 FAILED — class_create (%d)\n", ret);
        goto err_cdev;
    }
    printk(KERN_INFO "gpioled: Step 3 OK — class '%s' created\n", CLASS_NAME);

    /* Step 4: Create /dev/gpioled device node via udev */
    led_device = device_create(led_class, NULL, dev_number, NULL, DEVICE_NAME);
    if (IS_ERR(led_device)) {
        ret = PTR_ERR(led_device);
        printk(KERN_ERR "gpioled: Step 4 FAILED — device_create (%d)\n", ret);
        goto err_class;
    }
    printk(KERN_INFO "gpioled: Step 4 OK — /dev/%s created\n", DEVICE_NAME);

    /* Step 5: Request exclusive ownership of GPIO 24 (non-fatal)
     *
     * On kernels >= 6.x, gpio_request() may return -EPROBE_DEFER (-517)
     * even for valid pins due to the GPIO subsystem deferring probe. If
     * this happens, the module runs in simulation mode: /dev/gpioled is
     * fully operational but no physical pin is driven.
     */
    ret = gpio_request(GPIO_LED_PIN, "led_gpio");
    if (ret < 0) {
        printk(KERN_WARNING "gpioled: Step 5 WARN — gpio_request GPIO %d "
               "returned %d — running in simulation mode (no physical LED)\n",
               GPIO_LED_PIN, ret);
        gpio_available = 0;
    } else {
        /* Step 6: Configure GPIO 24 as output, initially LOW (LED off) */
        ret = gpio_direction_output(GPIO_LED_PIN, 0);
        if (ret < 0) {
            printk(KERN_WARNING "gpioled: Step 6 WARN — gpio_direction_output "
                   "returned %d — simulation mode\n", ret);
            gpio_free(GPIO_LED_PIN);
            gpio_available = 0;
        } else {
            gpio_available = 1;
            printk(KERN_INFO "gpioled: Step 5 OK — GPIO %d claimed\n",
                   GPIO_LED_PIN);
            printk(KERN_INFO "gpioled: Step 6 OK — GPIO %d set as output "
                   "(LOW)\n", GPIO_LED_PIN);
        }
    }

    if (gpio_available)
        printk(KERN_INFO "gpioled: ── module ready. /dev/%s open for "
               "commands (GPIO mode). ──\n", DEVICE_NAME);
    else
        printk(KERN_INFO "gpioled: ── module ready. /dev/%s open for "
               "commands (simulation mode — no GPIO). ──\n", DEVICE_NAME);

    return 0;

/* Error unwind — reverse order, only for fatal steps 1-4 */
err_class:
    class_destroy(led_class);
err_cdev:
    cdev_del(&led_cdev);
err_unreg:
    unregister_chrdev_region(dev_number, 1);
    return ret;
}

/*
 * led_driver_exit — runs on `sudo rmmod led_driver`.
 *
 * Releases every resource claimed in led_driver_init in reverse order.
 * GPIO cleanup is guarded by gpio_available so we don't free a pin we
 * never successfully claimed.
 */
static void __exit led_driver_exit(void)
{
    printk(KERN_INFO "gpioled: ── unloading module ─────────────────────────\n");

    /* Only touch GPIO if we successfully claimed it at init */
    if (gpio_available) {
        gpio_set_value(GPIO_LED_PIN, 0);    /* safety: drive LED LOW first */
        gpio_free(GPIO_LED_PIN);
        printk(KERN_INFO "gpioled: GPIO %d driven LOW and released\n",
               GPIO_LED_PIN);
    }

    device_destroy(led_class, dev_number);
    printk(KERN_INFO "gpioled: /dev/%s removed\n", DEVICE_NAME);

    class_destroy(led_class);
    printk(KERN_INFO "gpioled: class '%s' destroyed\n", CLASS_NAME);

    cdev_del(&led_cdev);
    unregister_chrdev_region(dev_number, 1);
    printk(KERN_INFO "gpioled: ── module unloaded cleanly ──────────────────\n");
}

module_init(led_driver_init);
module_exit(led_driver_exit);
