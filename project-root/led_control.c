#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>   
#include <fcntl.h>      
#include <signal.h>     

// Path to the character device created by led_driver.ko
#define DEVICE_PATH     "/dev/gpioled"

// Shared file written by led.py with the corrected Sense HAT temperature
#define SENSE_TEMP_PATH "/tmp/sense_temp"

// Mode file written by led.py: "1" = auto, "0" = manual override 
#define MODE_PATH       "/tmp/led_auto_mode"

// Temperature threshold in °C — must match TEMP_THRESHOLD in led.py (29 degrees)
#define TEMP_THRESHOLD  29.0f

// Period of time between each sensor read and LED control cycle (5 seconds)
#define POLL_INTERVAL_S 5

// Buffer size for reading device state response
#define RESPONSE_BUF    32

// Global variables
static int             fd      = -1;   
static volatile int    running =  1;  


// Signal handler
// handle_sigint - catches Ctrl-C command (SIGINT) for proper shutdown
// sets running to 0, main loop checks this value after each sleep()
static void handle_sigint(int sig)
{
    (void)sig;       /* suppress unused-parameter warning */
    running = 0;
}

// Temperature reader
// read_sense_temp: reads coorected ambient temperature from shared file /tmp/sense_temp
// returns temp as a floating value or -1.0f if file is not yet available
static float read_sense_temp(void)
{
    FILE  *fp;
    float  temp = -1.0f;

    fp = fopen(SENSE_TEMP_PATH, "r");
    if (fp == NULL)
        return -1.0f;       //file not ready yet — non-fatal, retry next cycle 

    if (fscanf(fp, "%f", &temp) != 1)
        temp = -1.0f;       // parse error — return sentinel

    fclose(fp);
    return temp;
}

int main(void)
{
    char    command[8];              // "ON" or "OFF" to send to the driver    
    char    response[RESPONSE_BUF]; // state string read back from the driver  
    float   temp;
    ssize_t n;

    printf("╔══════════════════════════════════════╗\n");
    printf("║  LED Control — CSC1107 Project 10    ║\n");
    printf("╚══════════════════════════════════════╝\n\n");
    printf("Device    : %s\n",   DEVICE_PATH);
    printf("Temp src  : %s\n",   SENSE_TEMP_PATH);
    printf("Threshold : %.1f °C\n", TEMP_THRESHOLD);
    printf("Poll rate : %d s\n\n", POLL_INTERVAL_S);

    //register SIGINT for a cleaner exit
    signal(SIGINT, handle_sigint);

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

    while (running) {

        /*
        Step 1: Check mode file
        skips cycle if the manual override is currently active
        led.py writes 0 to /tmp/led_auto_mode when dashboard's Turn ON / OFF button is pressed, writes 1 when auto mode renabled
        if file is absent, treated as auto
        */
        {
            FILE *mfp = fopen(MODE_PATH, "r");
            if (mfp) {
                int mode = 1;
                fscanf(mfp, "%d", &mode);
                fclose(mfp);
                if (mode == 0) {
                    sleep(POLL_INTERVAL_S);
                    continue;
                }
            }
        }

        // Step 2: Read correct Sense HAT ambient temperature
        temp = read_sense_temp();

        if (temp < 0.0f) {
            printf("[waiting] %s not ready — is PiServers/led_server.py running?\n",
                   SENSE_TEMP_PATH);
            sleep(POLL_INTERVAL_S);
            continue;
        }

        //Step 3: apply threshold to decide LED command
        if (temp > TEMP_THRESHOLD) {
            strncpy(command, "ON",  sizeof(command) - 1);
        } else {
            strncpy(command, "OFF", sizeof(command) - 1);
        }
        command[sizeof(command) - 1] = '\0';

        // Step 3: write to kernel module
        // System call invokes dev_write() in led_driver.c, which parses command string and drive GPIO 24 HIGH ("ON") or LOW ("OFF")
        n = write(fd, command, strlen(command));
        if (n < 0) {
            perror("Error: write() to " DEVICE_PATH);
            break;
        }

        // Step 4: read() from kernel module
        // dev_read() in led_driver returns LED status ON or OFF
        lseek(fd, 0, SEEK_SET);

        memset(response, 0, sizeof(response));
        n = read(fd, response, sizeof(response) - 1);
        if (n < 0) {
            perror("Error: read() from " DEVICE_PATH);
            break;
        }

        if (n > 0 && response[n - 1] == '\n')
            response[n - 1] = '\0';

        printf("%-10.1f %-5s %s\n", temp, command, response);

        sleep(POLL_INTERVAL_S);
    }

    printf("\n─────────────────────────────────────────\n");
    printf("Shutting down — sending OFF command...\n");

    if (fd >= 0) {
        write(fd, "OFF", 3);   /* turn LED off before exit */
        close(fd);             /* triggers dev_release() in led_driver.c */
    }

    printf("Device closed. Check dmesg for final kernel log.\n");
    return EXIT_SUCCESS;
}