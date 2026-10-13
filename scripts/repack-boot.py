#!/usr/bin/env python3
"""
repack-boot.py - Repack Android boot.img preserving AVB offset 0x4911000 and proven ramdisk

Usage:
  python3 scripts/repack-boot.py \
    --template Full.img \
    --kernel arch/arm64/boot/Image \
    --output spacewar-clean-boot.img \
    --avbtool scripts/avbtool.py
"""
import argparse
import os
import struct
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="Repack boot.img preserving AVB structure and proven ramdisk")
    parser.add_argument("--template", required=True, help="Path to template boot.img")
    parser.add_argument("--kernel", required=True, help="Path to new kernel Image")
    parser.add_argument("--output", default="spacewar-clean-boot.img", help="Path to output boot.img")
    parser.add_argument("--avbtool", default="scripts/avbtool.py", help="Path to avbtool.py")
    args = parser.parse_args()

    print("=== Repack boot.img (Preserve AVB Offset 0x4911000) ===")
    print(f"Template Image: {args.template}")
    print(f"Kernel Image:   {args.kernel}")
    print(f"Output Image:   {args.output}")

    with open(args.template, "rb") as f:
        tpl_data = f.read()

    # Check ANDROID! magic in header (4096 bytes)
    hdr = bytearray(tpl_data[:4096])
    magic = hdr[:8]
    if magic != b"ANDROID!":
        print(f"ERROR: Invalid header magic: {magic}")
        sys.exit(1)

    old_k_size = struct.unpack("<I", hdr[8:12])[0]
    old_r_size = struct.unpack("<I", hdr[12:16])[0]
    hdr_ver = struct.unpack("<I", hdr[40:44])[0]
    print(f"Template: header_version={hdr_ver}, kernel_size={old_k_size}, ramdisk_size={old_r_size}")

    # Extract proven untouched ramdisk from template
    old_k_padded = ((old_k_size + 4095) // 4096) * 4096
    r_offset = 4096 + old_k_padded
    ramdisk = tpl_data[r_offset : r_offset + old_r_size]
    print(f"Extracted untouched ramdisk: {len(ramdisk)} bytes from offset 0x{r_offset:x}")

    # Read new kernel
    with open(args.kernel, "rb") as f:
        new_kernel = f.read()
    new_k_size = len(new_kernel)
    print(f"New kernel size: {new_k_size} bytes")

    # Update boot header v3 (kernel_size and ramdisk_size)
    hdr[8:12] = struct.pack("<I", new_k_size)
    hdr[12:16] = struct.pack("<I", len(ramdisk))

    # Assemble raw image
    raw = bytearray()
    raw.extend(hdr)
    raw.extend(new_kernel)
    new_k_padded = ((new_k_size + 4095) // 4096) * 4096
    raw.extend(b"\x00" * (new_k_padded - new_k_size))
    raw.extend(ramdisk)
    r_padded = ((len(ramdisk) + 4095) // 4096) * 4096
    raw.extend(b"\x00" * (r_padded - len(ramdisk)))

    # Pad to exact AVB offset 0x4911000 if smaller
    TARGET_AVB_OFFSET = 0x4911000  # 76615680 bytes
    if len(raw) < TARGET_AVB_OFFSET:
        pad_len = TARGET_AVB_OFFSET - len(raw)
        raw.extend(b"\x00" * pad_len)
        print(f"Padded {pad_len} bytes to reach exact AVB offset 0x{TARGET_AVB_OFFSET:x}")
    elif len(raw) > TARGET_AVB_OFFSET:
        print(f"WARNING: Raw image size 0x{len(raw):x} exceeds target offset 0x{TARGET_AVB_OFFSET:x}")

    raw_size = len(raw)
    print(f"Raw boot image size: {raw_size} bytes (0x{raw_size:x})")

    with open(args.output, "wb") as f:
        f.write(raw)

    # Run avbtool to sign with exact hash footer
    avb_cmd = [
        sys.executable, args.avbtool, "add_hash_footer",
        "--image", args.output,
        "--partition_size", "100663296",
        "--partition_name", "boot",
        "--algorithm", "NONE",
        "--salt", "13f0b0127083a4a62c8897ee82ac3e0099f015d997031ef05fe759a8adf28f65",
        "--prop", "com.android.build.boot.fingerprint:Nothing/Spacewar/Spacewar:11/RKQ1.230824.001/2512191652:user/release-keys",
        "--prop", "com.android.build.boot.os_version:11",
        "--prop", "com.android.build.boot.security_patch:2025-05-05"
    ]
    print(f"Signing image with avbtool: {' '.join(avb_cmd)}")
    subprocess.run(avb_cmd, check=True)

    # Verify image and AVB offset
    final_size = os.path.getsize(args.output)
    with open(args.output, "rb") as f:
        f.seek(raw_size)
        avb0_magic = f.read(4)
        f.seek(final_size - 64)
        footer_magic = f.read(4)

    print("=== Verification ===")
    print(f"Final Image Size: {final_size} bytes (Expected: 100663296)")
    print(f"AVB0 magic at 0x{raw_size:x}: {avb0_magic} (Expected: b'AVB0')")
    print(f"AVBf footer at end: {footer_magic} (Expected: b'AVBf')")

    if final_size == 100663296 and avb0_magic == b"AVB0" and footer_magic == b"AVBf":
        print("✅ SUCCESS: Boot image repacked and verified successfully!")
    else:
        print("❌ ERROR: Verification failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
