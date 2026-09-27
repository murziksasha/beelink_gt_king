import os
import sys
import time
from aml_pack import unpack_aml_image, pack_aml_image
from sparse_tool import sparse_to_raw, raw_to_sparse
from modify_system import modify_system_image

BASE_IMG = "sbx_beelink_gtking_p0_aosp_9_20.img"
OUTPUT_IMG = "sbx_beelink_gtking_atv_RemontService.img"
UNPACK_DIR = "unpacked"
SYSTEM_PARTITION = os.path.join(UNPACK_DIR, "system.PARTITION")
SYSTEM_RAW = "system.raw"
EXTRA_APPS_DIR = "extra_apps"
TV_PERMS_DIR = "tv_permissions"
APK_APP_DIR = "apk_app"
BOOTANIM_DIR = "bootanim"

def build():
    start_time = time.time()
    print("\n" + "=" * 70)
    print("      CUSTOM AMLOGIC FIRMWARE BUILD PIPELINE (Beelink GT-King)")
    print("=" * 70)

    # Step 1: Check or unpack base image
    if not os.path.exists(UNPACK_DIR) or not os.path.exists(SYSTEM_PARTITION):
        print(f"\n[Step 1/5] Unpacking base firmware: {BASE_IMG}...")
        unpack_aml_image(BASE_IMG, UNPACK_DIR)
    else:
        print(f"\n[Step 1/5] Base partitions already present in '{UNPACK_DIR}'. Skipping unpack.")

    # Step 2: Convert sparse system.PARTITION to raw ext4 if not already done
    if not os.path.exists(SYSTEM_RAW):
        print(f"\n[Step 2/5] Converting system.PARTITION (Sparse -> Raw ext4)...")
        sparse_to_raw(SYSTEM_PARTITION, SYSTEM_RAW)
    else:
        print(f"\n[Step 2/5] Using existing '{SYSTEM_RAW}' ({os.path.getsize(SYSTEM_RAW):,} bytes).")

    # Step 3: Inject apps, permissions, Download folder APKs, and boot animation via WSL into system.raw
    print(f"\n[Step 3/5] Injecting custom apps, TV permissions, Download folder APKs, and boot animation...")
    modify_system_image(SYSTEM_RAW, EXTRA_APPS_DIR, TV_PERMS_DIR, apk_app_dir=APK_APP_DIR, bootanim_dir=BOOTANIM_DIR)

    # Step 4: Convert modified system.raw back to sparse system.PARTITION
    print(f"\n[Step 4/5] Recompressing system.raw -> {SYSTEM_PARTITION} (Sparse ext4)...")
    raw_to_sparse(SYSTEM_RAW, SYSTEM_PARTITION)

    # Step 5: Repack into final flashable Amlogic image
    print(f"\n[Step 5/5] Packaging all partitions into {OUTPUT_IMG}...")
    pack_aml_image(UNPACK_DIR, OUTPUT_IMG, template_img=BASE_IMG)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"BUILD FINISHED SUCCESSFULLY in {elapsed:.1f}s!")
    print(f"Output Image: {os.path.abspath(OUTPUT_IMG)}")
    print(f"File Size:    {os.path.getsize(OUTPUT_IMG):,} bytes")
    print("=" * 70)

if __name__ == "__main__":
    build()
