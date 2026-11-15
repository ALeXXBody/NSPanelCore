# KitchenPanel recovery — exact steps, ~20 minutes

## What happened (one line)
A display (TFT) update left the screen unbootable; the ESP side then went
dark too. Nothing here is experimental — every file below is checksummed
(see MD5SUMS) and the ESP firmware is the same 0.1.177 that ran fine before.

## What you need
- USB-to-TTL serial adapter (3.3V) + 4 dupont wires + a PC with Python
- Philips screwdriver, FAT32 microSD card (any size), mains OFF while open
- This folder (download it whole from the repo)

## A. ESP back to life (USB flash, 5 min)
1. Mains OFF. Open the panel, find the ESP32-C6-Zero serial header.
2. Wire adapter GND→GND, TX→RX, RX→TX (3.3V, never 5V).
3. Hold BOOT, tap RESET (or power on) to enter download mode.
4. On the PC: `pip install esptool`, then from this folder:
```
esptool.py --chip esp32c6 --port /dev/ttyUSB0 --baud 921600 write_flash \
  0x0 bootloader.bin \
  0x8000 partitions.csv \
  0x10000 firmware.bin \
  0x370000 littlefs.bin
```
(Windows: replace /dev/ttyUSB0 with COMx.)
5. Reset the board. The panel web UI comes back at its configured IP
   (or its setup AP if WiFi settings were wiped).

## B. Display back to life (SD card, 5 min)
1. Copy ONLY `blank.tft` onto the FAT32 microSD card.
2. Mains OFF. Insert the card into the display's SD slot, power on.
3. The display flashes itself and shows the QR screen. Power off, remove card.
4. From here the integration can push any TFT over WiFi again — but per
   RULE R5 nothing gets flashed without your explicit per-file approval.

## If A fails (esptool cannot connect)
- Swap TX/RX, check GND, try 115200 baud, try another USB cable/port
  (charge-only cables have no data wires — most common gotcha).
- If the ESP chip itself is dead, the board needs replacing; the display
  SD route (B) is still worth trying first.
