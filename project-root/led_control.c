/*
 * led_control.c — CSC1107 Project 10, user-space LED controller
 *
 * PURPOSE
 * ───────
 * Reads ambient temperature from /tmp/sense_temp (written every 2 s by
 * led.py using the Sense HAT sensor) and controls the physical LED via the
 * /dev/gpioled kernel driver using the write() and read() system calls.
 *
 * This is the primary demonstration of kernel ↔ user-space communication
 * required by the assignment brief.
 *
 * DATA FLOW PER CYCLE (every POLL_INTERVAL_S seconds)
 * ─────────────────────────────────────────────────────
 *   /tmp/sense_temp   →  read_sense_temp()   →  corrected ambient °C
 *   threshold check   →  "ON" or "OFF"       →  command string
 *   write(fd, cmd)    →  dev_write()  [kernel] →  gpio_set_value() → LED
 *   read(fd, buf)     ←  dev_read()   [kernel] ←  "LED:ON\n"/"LED:OFF\n"
 *   printf(status)    →  stdout
 *
 * TEMPERATURE SOURCE
 * ──────────────────
 * /tmp/sense_temp is written by led.py's Sense HAT monitor loop. It contains
 * the CPU-corrected ambient temperature as a float (e.g. "27.34\n"). Using
 * this file — rather than /sys/class/thermal/thermal_zone0/temp — ensures
 * that the C program and the Python layer use the same ambient reading and
 * apply the same threshold, producing consistent LED behaviour.
 *
 * USAGE
 * ─────
 *   gcc -Wall -o led_control led_control.c
 *   sudo ./led_control
 *
 * REQUIREMENTS
 * ─────────────
 *   led_driver.ko must be loaded:  sudo insmod led_driver.ko
 *   led.py must be running:        python led_server.py  (writes sense_temp)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>     /* open, read, write, close, sleep, lseek  */
#include <fcntl.h>      /* O_RDWR                                  */
#include <signal.h>     /* signal, SIGINT                          */

/* ── Configuration ────────────────────────────────────────────────────────── */

/* Path to the character device created by led_driver.ko */
#define DEVICE_PATH     "/dev/gpioled"

/* Shared file written by led.py with the corrected Sense HAT temperature */
#define SENSE_TEMP_PATH "/tmp/sense_temp"

/* Temperature threshold in °C — must match TEMP_THRESHOLD in led.py */
#define TEMP_THRESHOLD  29.0f

/* Seconds between each sensor read + LED control cycle */
#define POLL_INTERVAL_S 5

/* Size of buffer for reading the device state response */
#define RESPONSE_BUF    32

/* ── Globals ──────────────────────────────────────────────────────────────── */
static int             fd      = -1;    /* /dev/gpioled file descriptor        */
static volatile int    running =  1;    /* cleared by SIGINT to break the loop */

/* ── Signal handler ───────────────────────────────────────────────────────── */

/*
 * handle_sigint — catches Ctrl-C (SIGINT) for graceful shutdown.
 * Sets running = 0; the main loop checks this after each sleep().
 */
static void handle_sigint(int sig)
{
    (void)sig;       /* suppress unused-parameter warning */
    running = 0;
}

/* ── Temperature reader ───────────────────────────────────────────────────── */

/*
 * read_sense_temp — reads the corrected ambient temperature from the shared
 * file /tmp/sense_temp written by the Sense HAT monitor in led.py.
 *
 * Returns the temperature as a float, or -1.0f if the file is not yet
 * available (i.e. led.py has not started or not completed its first read).
 */
static float read_sense_temp(void)
{
    FILE  *fp;
    float  temp = -1.0f;

    fp = fopen(SENSE_TEMP_PATH, "r");
    if (fp == NULL)
        return -1.0f;       /* file not ready yet — non-fatal, retry next cycle */

    if (fscanf(fp, "%f", &temp) != 1)
        temp = -1.0f;       /* parse error — return sentinel */

    fclose(fp);
    return temp;
}

/* ── Main ─────────────────────────────────────────────────────────────────── */

int main(void)
{
    char    command[8];              /* "ON" or "OFF" to send to the driver    */
    char    response[RESPONSE_BUF]; /* state string read back from the driver  */
    float   temp;
    ssize_t n;

    printf("╔══════════════════════════════════════╗\n");
    printf("║  LED Control — CSC1107 Project 10    ║\n");
    printf("╚══════════════════════════════════════╝\n\n");
    printf("Device    : %s\n",   DEVICE_PATH);
    printf("Temp src  : %s\n",   SENSE_TEMP_PATH);
    printf("Threshold : %.1f °C\n", TEMP_THRESHOLD);
    printf("Poll rate : %d s\n\n", POLL_INTERVAL_S);

    /* Register SIGINT handler for clean Ctrl-C exit */
    signal(SIGINT, handle_sigint);

    /* ── Open the kernel device node ─────────────────────────────────────── */
    /*
     * open() triggers dev_open() in led_driver.c.
     * O_RDWR: we will both write commands and read state.
     */
    fd = open(DEVICE_PATH, O_RDWR);
    if (fd < 0) {
        perror("Error: open(" DEVICE_PATH ")");
        fprintf(stderr,
                "Is led_driver.ko loaded? "
                "Run: sudo insmod led_driver.ko\n");
        return EXIT_FAILURE;
    }
    printf("Opened %s successfully.\n\n", DEVICE_PATH);
    printf("%-10s %-5s %s\n", "Temp (°C)", "Cmd", "Kernel response");
    printf("─────────────────────────────────────────\n");

    /* ── Main polling loop ────────────────────────────────────────────────── */
    while (running) {

        /* Step 1: Get corrected Sense HAT ambient temperature */
        temp = read_sense_temp();

        if (temp < 0.0f) {
            printf("[waiting] %s not ready — is PiServers/led_server.py running?\n",
                   SENSE_TEMP_PATH);
            sleep(POLL_INTERVAL_S);
            continue;
        }

        /* Step 2: Apply threshold to decide LED command */
        if (temp > TEMP_THRESHOLD) {
            strncpy(command, "ON",  sizeof(command) - 1);
        } else {
            strncpy(command, "OFF", sizeof(command) - 1);
        }
        command[sizeof(command) - 1] = '\0';

        /* ── Step 3: write() to kernel module ────────────────────────────── */
        /*
         * This system call crosses the user/kernel boundary and invokes
         * dev_write() in led_driver.c, which parses the command string
         * and drives GPIO 24 HIGH ("ON") or LOW ("OFF").
         */
        n = write(fd, command, strlen(command));
        if (n < 0) {
            perror("Error: write() to " DEVICE_PATH);
            break;
        }

        /* ── Step 4: read() from kernel module ───────────────────────────── */
        /*
         * dev_read() in led_driver.c returns "LED:ON\n" or "LED:OFF\n".
         * The driver uses the file offset to detect repeated reads (returns
         * EOF once the string has been sent). lseek() resets the offset so
         * each iteration gets a fresh read.
         */
        lseek(fd, 0, SEEK_SET);

        memset(response, 0, sizeof(response));
        n = read(fd, response, sizeof(response) - 1);
        if (n < 0) {
            perror("Error: read() from " DEVICE_PATH);
            break;
        }

        /* Strip trailing newline for tidy output */
        if (n > 0 && response[n - 1] == '\n')
            response[n - 1] = '\0';

        /* Step 5: Print status line */
        printf("%-10.1f %-5s %s\n", temp, command, response);

        sleep(POLL_INTERVAL_S);
    }

    /* ── Cleanup: drive LED off and close device ──────────────────────────── */
    printf("\n─────────────────────────────────────────\n");
    printf("Shutting down — sending OFF command...\n");

    if (fd >= 0) {
        write(fd, "OFF", 3);   /* turn LED off before exit */
        close(fd);             /* triggers dev_release() in led_driver.c */
    }

    printf("Device closed. Check dmesg for final kernel log.\n");
    return EXIT_SUCCESS;
}