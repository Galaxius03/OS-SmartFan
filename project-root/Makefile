# Makefile — CSC1107 Project 10, led_driver kernel module
#
# Usage:
#   make        — compile led_driver.c → led_driver.ko
#   make clean  — remove all build artefacts
#
# obj-m declares led_driver.o as an out-of-tree kernel module.
# $(shell uname -r) inserts the running kernel version at build time.

obj-m += led_driver.o

KDIR := /lib/modules/$(shell uname -r)/build

all:
	make -C $(KDIR) M=$(PWD) modules

clean:
	make -C $(KDIR) M=$(PWD) clean
