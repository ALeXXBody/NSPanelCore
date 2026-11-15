# USB recovery set — DemoPanel unbrick

Fresh, consistent build from this repo HEAD (firmware 0.1.177 + current
LittleFS + bootloader + partition table), plus the proven blank display
file (md5-verified against the Blackymas official release).

## You need
- USB-to-TTL serial adapter (3.3V), Espressif `esptool` (`pip install esptool`)
- Panel opened with MAINS OFF, ESP32-C6 serial console accessible
  (TX/RX/GND, boot into download mode per board: hold BOOT, tap RESET)

## Flash the ESP (wipes and restores everything)
```
esptool.py --chip esp32c6 --port /dev/ttyUSB0 --baud 921600 write_flash \
  0x0 bootloader.bin \
  0x8000 partitions.csv \
  0x10000 firmware.bin \
  0x370000 littlefs.bin
```
Verify with `esptool.py ... verify_flash` if you want. Reboot: the panel
should come back on WiFi (or its setup AP if settings were wiped).

## If the display still shows System Data ERROR: SD-card rescue
- Copy `blank.tft` to a FAT32 microSD card, insert into the display's SD
  slot, power on. The display flashes itself and boots the blank screen.
- Then re-flash the real TFT over WiFi/MQTT from the integration as usual.

## Files
See MD5SUMS. `blank.tft` md5 must be
`31ed23faf5db06e2f36009fc0940354e` (official Blackymas release, verified).
