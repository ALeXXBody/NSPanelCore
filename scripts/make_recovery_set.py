#!/usr/bin/env python3
"""Build the NSPanel Core recovery set for one firmware release.

P310 rule: the recovery set is GENERATED, never hand-copied. Every firmware
release regenerates it (this script) and the webtool serves exactly these
parts — so the files a stranded panel is flashed with can never drift from
the release.

Outputs (into --out):
  recovery-merged-flash-<ver>.bin   single image written at offset 0x0
                                    (bootloader 0x1000, partitions 0x8000,
                                    OTA-slot reset 0xE000, app 0x10000,
                                    data file 0x370000)
  bootloader_native.bin / partitions_native.bin / ota_data_initial.bin /
  native_firmware.bin / data_file.bin   the webtool's per-part files

Usage:
  scripts/make_recovery_set.py --version 0.1.4 \
      --build-dir firmware-native/.pio/build/native_idf5 \
      --app firmware/releases/v0.1.4/native-firmware-0.1.4.bin \
      --data firmware/releases/v0.1.4/data_file.bin \
      --out /tmp/recovery-set
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct

APP_OFFSET = 0x10000
DATA_OFFSET = 0x370000
FLASH_SIZE = 0x400000  # 4 MB


def place(img: bytearray, offset: int, blob: bytes, name: str) -> None:
    need = offset + len(blob)
    if len(img) < need:
        img.extend(bytes(need - len(img)))
    img[offset:offset + len(blob)] = blob
    print(f"  {name}: {len(blob)} bytes at 0x{offset:x}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--build-dir", required=True,
                    help="the firmware-native pio build dir (bootloader/partitions/otadata)")
    ap.add_argument("--app", required=True, help="the release app .bin")
    ap.add_argument("--data", required=True, help="the release data .bin")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    build = pathlib.Path(args.build_dir)
    bootloader = (build / "bootloader.bin").read_bytes()
    partitions = (build / "partitions.bin").read_bytes()
    otadata = (build / "ota_data_initial.bin").read_bytes()
    app = pathlib.Path(args.app).read_bytes()
    data = pathlib.Path(args.data).read_bytes()

    # integrity gates — the P118 lesson (bootloader at 0x0) and the P310
    # incident (wrong app / missing slot reset) must never repeat
    assert bootloader[0] == 0xE9, "bootloader image magic missing"
    assert partitions[0:2] == b"\xaa\x50", "partition table magic missing"
    assert app[0] == 0xE9, "app image magic missing"
    desc = app[0x20:0x120]
    assert b"nspanel_core" in desc, "app is not an NSPanel Core build"
    ver = args.version.encode()
    assert ver in desc, f"app descriptor does not carry version {args.version}"
    assert all(b == 0xFF for b in otadata), \
        "ota_data_initial must be fully erased (fresh slot selection)"

    img = bytearray()
    place(img, 0x1000, bootloader, "bootloader")
    place(img, 0x8000, partitions, "partitions")
    place(img, 0xE000, otadata, "ota_data_initial (slot reset)")
    place(img, APP_OFFSET, app, "app")
    place(img, DATA_OFFSET, data, "data file")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    merged = out / f"recovery-merged-flash-{args.version}.bin"
    merged.write_bytes(bytes(img))
    (out / "bootloader_native.bin").write_bytes(bootloader)
    (out / "partitions_native.bin").write_bytes(partitions)
    (out / "ota_data_initial.bin").write_bytes(otadata)
    (out / "native_firmware.bin").write_bytes(app)
    (out / "data_file.bin").write_bytes(data)

    # post-write verification of the MERGED image itself
    m = merged.read_bytes()
    assert len(m) == DATA_OFFSET + len(data), "merged image size wrong"
    assert m[0x1000] == 0xE9, "merged: bootloader magic missing at 0x1000"
    assert m[0x8000:0x8002] == b"\xaa\x50", "merged: partition magic missing"
    assert m[0x10000] == 0xE9, "merged: app magic missing at 0x10000"
    assert m[0xE000:0xE000 + 255] == b"\xff" * 255, "merged: otadata not erased"

    md5 = hashlib.md5(m).hexdigest()
    print(f"recovery set written to {out}")
    print(f"recovery-merged-flash-{args.version}.bin  md5 {md5}")


if __name__ == "__main__":
    main()
