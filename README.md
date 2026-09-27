# Beelink GT-King (Amlogic S922X) Custom Firmware Toolchain

[![Platform](https://img.shields.io/badge/Platform-Amlogic%20S922X-blue.svg)](https://www.amlogic.com/)
[![Target](https://img.shields.io/badge/Target-Beelink%20GT--King-orange.svg)](https://www.bee-link.com/)
[![OS](https://img.shields.io/badge/OS-Android%209%20%2F%20ATV%20Leanback-green.svg)](https://source.android.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

An automated, cross-platform firmware engineering toolchain for unpacking, modifying, customizing, and repacking Android TV / SlimBOX firmware images for the **Beelink GT-King (Amlogic S922X)** TV box.

The toolchain operates without requiring official proprietary closed-source Amlogic Linux SDK tools, utilizing pure-Python binary handlers and WSL2 for ext4 loop-device modifications.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Project Structure](#project-structure)
- [Detailed Script Descriptions](#detailed-script-descriptions)
- [Directory Breakdown](#directory-breakdown)
- [Boot Animation Signature](#boot-animation-signature)
- [Build Workflow & Flashing](#build-workflow--flashing)
- [Technical Deep Dive](#technical-deep-dive)
  - [Amlogic Firmware Header Structure](#amlogic-firmware-header-structure)
  - [Android Sparse to Raw Ext4 Pipeline](#android-sparse-to-raw-ext4-pipeline)
  - [APK Injection & 32-bit Native Library Rules](#apk-injection--32-bit-native-library-rules)
  - [Auto-Deploy to Android Download Directory](#auto-deploy-to-android-download-directory)
- [Roadmap](#roadmap)
- [License & Credits](#license--credits)

---

## Overview

Customizing Amlogic TV box firmwares historically required running unstable 32-bit Windows GUI utilities (e.g. `CustomizationTool.exe`) or bulky Linux virtual machines.

This repository provides an automated, programmatic pipeline that:
1. Unpacks official or community `.img` firmware archives into raw partition components.
2. Decompresses Android sparse images (`system.PARTITION`) into raw ext4 filesystem disks (`system.raw`).
3. Injects custom applications, native `.so` libraries, Android TV / Leanback system permissions, first-boot downloader scripts, and branded boot animations.
4. Recompresses modified filesystems into sparse partition blocks.
5. Rebuilds standard-compliant Amlogic flashable images matching `AmlImagePack.dll` specifications for direct flashing via **Amlogic USB Burning Tool**.

---

## Key Features

- **Pure Python Amlogic Unpacker & Packer (`aml_pack.py`, `aml_unpack.py`):**
  - Full binary parser for Amlogic image headers (`0x27B51956` magic).
  - Accurate inverted stream CRC32 calculation (`~crc32 & 0xFFFFFFFF`) required by Amlogic USB Burning Tool.
  - Template-based partition rebuild preserving partition tables, sizes, and offsets.
- **Sparse Image Processor (`sparse_tool.py`):**
  - High-speed bi-directional sparse-to-raw and raw-to-sparse converter.
  - Generates standard Android Sparse ext4 images (`0xED26FF3A` magic) without external Android SDK dependencies.
- **System Customization & App Injection (`modify_system.py`):**
  - Mounts ext4 filesystem via WSL2 loopback with root permissions (`0:0`).
  - **Sanitization Engine:** Strips illegal characters, version strings, spaces, and Unicode symbols (`®`, `™`) to meet Android Package Manager directory requirements (`<DirName>/<DirName>.apk`).
  - **Native Library Extraction:** Extracts 32-bit native libraries (`lib/armeabi-v7a/*.so`) directly into `/system/app/<DirName>/lib/arm/` so the Android runtime loads them on system apps without crashes.
  - **Android TV Permissions Injection:** Upgrades standard AOSP installations with Google TV / Leanback capabilities (`android.software.leanback.xml`, `privapp-permissions-*.xml`).
  - **First-Boot Download Installer:** Automatic staging and deployment service that places specified APKs directly into `/sdcard/Download` (`/data/media/0/Download`) upon initial boot with proper permissions (`1023:1023 media_rw`) and MediaScanner indexing.
- **Signature Boot Animation (`bootanim/`):**
  - Custom boot animation with custom logo ("Remont Service") automatically baked into `/system/media/bootanimation.zip` at `0644 root:root`.
  - Includes full source frames (`part0/`, `part1/`, `desc.txt`).

---

## Project Structure

```
firmWare/
├── .gitignore                      # Strict ignore rules for large binaries (.img, .raw, .apk)
├── AGENTS.md                       # Build discipline rules & Amlogic specifications
├── README.md                       # Comprehensive documentation & architectural manual
├── build_firmware.py               # Main end-to-end automated build pipeline
├── build_firmware.bat              # One-click Windows build launcher
├── aml_pack.py                     # Amlogic firmware image unpacker & packer engine
├── aml_unpack.py                   # Standalone CLI unpacker utility
├── modify_system.py                # WSL2 system partition modification & injection engine
├── sparse_tool.py                  # Android sparse <-> raw ext4 conversion tool
├── build.prop                      # Reference / modified build properties
├── apk_app/                        # Target directory for APKs copied to user /sdcard/Download
│   ├── .gitkeep
│   └── README.txt
├── bootanim/                       # Custom signature boot animation & source frames
│   ├── bootanimation.zip           # Ready-to-inject compressed boot animation
│   ├── desc.txt                    # Animation resolution and frame rate parameters
│   ├── part0/                      # Intro frames (sbx_bootanim_000.jpg - 024.jpg)
│   └── part1/                      # Loop frames (sbx_bootanim_025.jpg - 064.jpg)
├── extra_apps/                     # System apps injected into /system/app/
│   └── .gitkeep
└── tv_permissions/                 # Android TV & Leanback permission XML declarations
    ├── android.hardware.type.television.xml
    ├── android.software.leanback.xml
    ├── android.software.live_tv.xml
    ├── com.google.android.tv.installed.xml
    ├── privapp-permissions-atv.xml
    └── privapp-permissions-google.xml
```

---

## Detailed Script Descriptions

### `build_firmware.py`
The master orchestrator. Runs the full 5-stage automated pipeline:
1. **Unpack:** Reads `sbx_beelink_gtking_p0_aosp_9_20.img` and extracts all 28 partitions into `unpacked/`.
2. **Decompress:** Converts `unpacked/system.PARTITION` (sparse ext4) to `system.raw` (raw ext4).
3. **Modify:** Launches `modify_system.py` via WSL to inject apps, permissions, download files, and boot animations.
4. **Recompress:** Converts `system.raw` back into a sparse `system.PARTITION`.
5. **Pack:** Repacks all partitions into the final flashable image (`sbx_beelink_gtking_atv_RemontService.img`).

### `build_firmware.bat`
A batch launcher for Windows environments. Executes `python build_firmware.py` and provides colored error status and pause prompts.

### `aml_pack.py` & `aml_unpack.py`
Low-level binary tools for Amlogic `.img` archives.
- **`unpack_aml_image(img_path, output_dir)`:** Scans headers and unpacks all images (e.g. `bootloader.PARTITION`, `boot.PARTITION`, `recovery.PARTITION`, `system.PARTITION`, `vendor.PARTITION`, `dtbo.PARTITION`, etc.).
- **`pack_aml_image(unpack_dir, output_img, template_img)`:** Rebuilds a compliant `.img` using the partition layout from `template_img`, computing:
  - Header CRC32 checksum.
  - Image size alignment.
  - Item headers (576 bytes each).

### `modify_system.py`
Linux/WSL engine that performs in-place modifications on `system.raw`:
- Mounts `system.raw` via loopback at `/tmp/sysmount`.
- Auto-detects standard root vs system-as-root layouts (`/tmp/sysmount/system` vs `/tmp/sysmount`).
- Stages and sanitizes APKs.
- Extracts `armeabi-v7a` native libraries into `/system/app/<AppName>/lib/arm/`.
- Injects Android TV Leanback permissions into `/system/etc/permissions/`.
- Deploys `copy_apk_app.sh` and `/system/etc/init/copy_apk_app.rc` to copy files to `/data/media/0/Download`.
- Injects `bootanimation.zip` into `/system/media/bootanimation.zip`.
- Safely unmounts and syncs filesystem caches.

### `sparse_tool.py`
Provides streaming conversion between Android Sparse (`0xED26FF3A`) and raw ext4 disk images:
- **`sparse_to_raw(sparse_path, raw_path)`:** Parses sparse chunks (`RAW`, `FILL`, `DONT_CARE`, `CRC32`) and writes linear disk images.
- **`raw_to_sparse(raw_path, sparse_path, blk_sz=4096)`:** Scans raw disk blocks, identifies zero/unallocated blocks, and emits compact sparse structures, reducing 2.1 GB disks down to only allocated space (~1.7 GB).

---

## Directory Breakdown

| Directory | Purpose | Git Status |
| :--- | :--- | :--- |
| `bootanim/` | Custom signature boot animation & frame sources | **Tracked** |
| `extra_apps/` | APKs to be installed as system apps (`/system/app/`) | Gitignored (except `.gitkeep`) |
| `apk_app/` | APKs & user files copied to `/sdcard/Download` on first boot | Gitignored (except `.gitkeep`) |
| `tv_permissions/` | Android TV Leanback XML permission profiles | **Tracked** |
| `tv_priv_apps/` | Privileged system apps with pre-extracted libraries | Gitignored |
| `unpacked/` | Working directory for unpacked partition images | Gitignored |

---

## Boot Animation Signature

The repository includes a custom signature boot animation in `bootanim/`:
- **Resolution:** 915x638 @ 30 FPS (`desc.txt`).
- **Structure:**
  - `part0/`: Intro phase (frames 0 to 24), runs once (`c 1 0 part0`).
  - `part1/`: Loop phase (frames 25 to 64), loops infinitely until Android finishes booting (`f 0 0 part1 9`).
- **Pre-packaged:** `bootanim/bootanimation.zip` is ready for direct injection into `/system/media/bootanimation.zip`.
- **Automatic Injection:** Handled automatically during Step 3 of the build process.

---

## Build Workflow & Flashing

### Prerequisites
1. **Windows 10/11** with **WSL2** installed (Ubuntu or Alpine Linux).
2. **Python 3.10+** (with standard libraries `struct`, `os`, `shutil`, `zlib`).
3. **Amlogic USB Burning Tool v2.2.0+** or **v3.2.0+**.
4. Male-to-Male USB Cable for flashing the Beelink GT-King.

### Step-by-Step Instructions

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/murziksasha/beelink_gt_king.git
   cd beelink_gt_king
   ```

2. **Add Base Firmware Image:**
   Place the stock or base firmware image into the project root:
   ```text
   sbx_beelink_gtking_p0_aosp_9_20.img
   ```

3. **Configure Apps:**
   - **For System Apps (non-uninstallable):** Copy APK files into `extra_apps/`.
   - **For User Apps (available in Download folder):** Copy APK files into `apk_app/`.

4. **Execute Build:**
   Double-click `build_firmware.bat` or run:
   ```powershell
   python build_firmware.py
   ```

5. **Flash to Beelink GT-King:**
   - Open **Amlogic USB Burning Tool**.
   - Load File -> Import Image -> select `sbx_beelink_gtking_atv_RemontService.img`.
   - Ensure `Erase flash (Normal erase)` and `Erase bootloader` are checked.
   - Hold the recovery button (pinhole underneath the GT-King) with a toothpick, connect the USB-A cable to the OTG USB port, and click **Start**.

---

## Technical Deep Dive

### Amlogic Firmware Header Structure

Amlogic firmware packages (`.img`) use a proprietary multi-item binary archive layout:

```
+-------------------------------------------------------------+
| Header (64 Bytes)                                           |
|   0x00 - 0x03 : Inverted CRC32 Checksum (~crc32(bytes[4:])) |
|   0x04 - 0x07 : Header Version (usually 1)                  |
|   0x08 - 0x0B : Magic Constant (0x27B51956)                 |
|   0x0C - 0x0F : Total File Size (uint32)                    |
|   0x18 - 0x1B : Partition / Item Count (strictly 28 items)  |
+-------------------------------------------------------------+
| Item Headers (576 Bytes x 28 Items)                         |
|   0x00 - 0x07 : Magic ("AML_HEAD")                          |
|   0x10 - 0x17 : File Data Offset (uint64)                   |
|   0x18 - 0x1F : File Data Size (uint64)                     |
|   0x20 - 0x3F : File Extension / Type (e.g. PARTITION, USB) |
|   0x120 - 0x13F: Partition Base Name (e.g. system, boot)    |
+-------------------------------------------------------------+
| Partition Data Payloads                                     |
|   ... (Raw partition streams, byte-aligned)                 |
+-------------------------------------------------------------+
```

### Android Sparse to Raw Ext4 Pipeline

Android fastboot/flashing systems use sparse images:
- **`CHUNK_RAW (0xCAC1)`**: Uncompressed ext4 data blocks.
- **`CHUNK_FILL (0xCAC2)`**: Repeating 4-byte patterns (e.g. zero blocks).
- **`CHUNK_DONT_CARE (0xCAC3)`**: Unallocated blocks skipped without writing to disk.

`sparse_tool.py` translates chunks directly to a linear disk image, allowing standard ext4 mounting in WSL without requiring `simg2img` or `img2simg` binaries.

### APK Injection & 32-bit Native Library Rules

1. **System App Directory Standard:**
   Android enforces that `/system/app/<DirName>/` must contain `<DirName>.apk`. Any mismatch or spaces in filenames will result in Package Manager ignoring the package.
2. **Native Libraries (`.so`):**
   Unlike user apps installed from the Play Store, system apps (`FLAG_SYSTEM`) do **not** have their compressed `.so` files unpacked to `/data/app-lib/` at boot.
   The toolchain inspects each APK's internal `lib/` directory and extracts 32-bit libraries (`lib/armeabi-v7a/*.so`) directly to `/system/app/<DirName>/lib/arm/`.
3. **Permissions:**
   Directories are set to `0755` and files to `0644`, owned by `0:0 (root:root)`.

### Auto-Deploy to Android Download Directory

For applications that users may want to install, uninstall, or update freely, the toolchain installs a custom Android init service:
- Stages APKs in `/system/etc/apk_app/`.
- Installs `/system/bin/copy_apk_app.sh` triggered by `sys.boot_completed=1` via `/system/etc/init/copy_apk_app.rc`.
- Copies files into `/data/media/0/Download/` with ownership `1023:1023 (media_rw:media_rw)` and mode `775/664`.
- Emits `android.intent.action.MEDIA_SCANNER_SCAN_FILE` broadcasts to trigger instant detection in Android file managers.
- Maintains a version marker (`/data/media/0/.apk_app_version`) to prevent redundant copying on subsequent boots.

---

## Roadmap

- [x] **Phase 1: Core Toolchain & Automation**
  - [x] Pure-Python Amlogic image unpacker and packer.
  - [x] Pure-Python Android sparse <-> raw ext4 converter.
  - [x] Automated WSL2 loopback ext4 system modification engine.
  - [x] Pre-flash image integrity validation (CRC32, magic, item headers).

- [x] **Phase 2: Android TV Ecosystem & Signature Branding**
  - [x] Android TV / Leanback XML permissions injection.
  - [x] APK name sanitization and 32-bit native `.so` extraction.
  - [x] Background boot-copy service to `/sdcard/Download`.
  - [x] Branded boot animation injection ("Remont Service" signature).

- [ ] **Phase 3: Advanced Optimization & Device Tree Tuning (Upcoming)**
  - [ ] **Device Tree Blob (`_aml_dtb`, `meson1.dtb`) Customization:**
    - CPU thermal throttling adjustments for the Amlogic S922X (A73 + A53 clusters).
    - Custom fan speed curves and cooling policies.
  - [ ] **Kernel & Boot Image Modification (`boot.PARTITION`):**
    - Automated integration of Magisk root patching directly into `boot.img`.
    - Custom init scripts for hardware performance governor tuning.
  - [ ] **Vendor Partition Optimization (`vendor.PARTITION`):**
    - Updated Broadcom / Realtek Wi-Fi and Bluetooth firmware blobs for improved 5GHz stability.
  - [ ] **One-Click Web GUI / Desktop Interface:**
    - Lightweight browser-based control dashboard for non-technical users to drag-and-drop APKs and build customized firmwares.

---

## License & Credits

Developed for the **Beelink GT-King (S922X)** community.
Firmware base: **SlimBOX OS (AOSP / ATV 9.0)**.
Toolchain: Custom Python & WSL implementation.
