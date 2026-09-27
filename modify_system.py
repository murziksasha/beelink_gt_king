import os
import re
import sys
import time
import shutil
import zipfile
import subprocess

def win_to_wsl_path(win_path: str) -> str:
    abs_path = os.path.abspath(win_path)
    drive, rest = os.path.splitdrive(abs_path)
    drive_letter = drive[0].lower()
    linux_rest = rest.replace('\\', '/')
    return f"/mnt/host/{drive_letter}{linux_rest}"

def sanitize_app_name(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    # Remove unicode trademark/copyright symbols
    name = re.sub(r'[\u00ae\u00a9\u2122]', '', name)
    # Strip trailing version suffixes (e.g. -4.8.0, _v1.0.0, .141.Client-release, +v2.10.0)
    name = re.sub(r'[-_+\. ]*(?:ver|v)?\d+(?:[\._]\d+)*.*$', '', name, flags=re.IGNORECASE)
    # Normalize remaining non-alphanumeric chars to underscores
    name = re.sub(r'[^\w]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name if name else "App"

def prepare_staging_apps(extra_apps_dir: str, staging_dir: str):
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    print(f"\n[Staging] Preparing extra apps from '{extra_apps_dir}'...")
    for root, _, files in os.walk(extra_apps_dir):
        for file in files:
            if not file.lower().endswith(".apk"):
                continue

            src_apk = os.path.join(root, file)
            app_dir_name = sanitize_app_name(file)
            target_app_dir = os.path.join(staging_dir, app_dir_name)
            os.makedirs(target_app_dir, exist_ok=True)
            target_apk = os.path.join(target_app_dir, f"{app_dir_name}.apk")

            # Copy APK with sanitized name
            shutil.copy2(src_apk, target_apk)

            # Extract 32-bit native libraries into lib/arm/
            extracted_count = 0
            with zipfile.ZipFile(src_apk, 'r') as zf:
                all_libs = [f for f in zf.namelist() if f.endswith('.so')]
                v7a_libs = [f for f in all_libs if f.startswith('lib/armeabi-v7a/')]
                v7_libs = [f for f in all_libs if f.startswith('lib/armeabi/')]
                arm64_libs = [f for f in all_libs if f.startswith('lib/arm64-v8a/')]

                target_libs = v7a_libs if v7a_libs else v7_libs

                if target_libs:
                    lib_arm_dir = os.path.join(target_app_dir, "lib", "arm")
                    os.makedirs(lib_arm_dir, exist_ok=True)
                    for lib in target_libs:
                        lib_name = os.path.basename(lib)
                        out_so = os.path.join(lib_arm_dir, lib_name)
                        with zf.open(lib) as src_so, open(out_so, "wb") as dst_so:
                            shutil.copyfileobj(src_so, dst_so)
                        extracted_count += 1
                elif arm64_libs:
                    print(f"  [!] Warning: '{file}' only has 64-bit native libs (arm64-v8a). Will not load on 32-bit OS.")

            print(f"  -> {file} => {app_dir_name}/{app_dir_name}.apk ({extracted_count} native .so extracted)")

def prepare_staging_apk_app(apk_app_dir: str, staging_dir: str):
    """Stages APKs and other files destined for the Android Download folder."""
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    copied_count = 0
    if os.path.exists(apk_app_dir):
        print(f"\n[Staging] Preparing Download folder files from '{apk_app_dir}'...")
        for item in os.listdir(apk_app_dir):
            if item in [".gitkeep", ".gitignore"]:
                continue
            src_path = os.path.join(apk_app_dir, item)
            dst_path = os.path.join(staging_dir, item)
            if os.path.isfile(src_path):
                shutil.copy2(src_path, dst_path)
                copied_count += 1
                print(f"  -> Added file for Download: {item}")
            elif os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
                copied_count += 1
                print(f"  -> Added folder for Download: {item}/")

    version_str = str(int(time.time()))
    with open(os.path.join(staging_dir, ".version"), "w", encoding="utf-8") as f:
        f.write(version_str)

    print(f"[Staging] Download folder items prepared: {copied_count}")

def modify_system_image(raw_image_path: str, extra_apps_dir: str, tv_perms_dir: str, modified_build_prop: str = None, apk_app_dir: str = "apk_app"):
    print("=" * 60)
    print("Modifying system.raw image via WSL...")
    print("=" * 60)

    if not os.path.exists(raw_image_path):
        raise FileNotFoundError(f"Raw system image not found: {raw_image_path}")

    staging_dir = os.path.abspath("tmp_staging_apps")
    prepare_staging_apps(extra_apps_dir, staging_dir)

    staging_apk_dir = os.path.abspath("tmp_staging_apk_app")
    prepare_staging_apk_app(apk_app_dir, staging_apk_dir)

    wsl_raw = win_to_wsl_path(raw_image_path)
    wsl_staging = win_to_wsl_path(staging_dir)
    wsl_staging_apk = win_to_wsl_path(staging_apk_dir)
    wsl_perms = win_to_wsl_path(tv_perms_dir) if tv_perms_dir and os.path.exists(tv_perms_dir) else None
    wsl_prop = win_to_wsl_path(modified_build_prop) if modified_build_prop and os.path.exists(modified_build_prop) else None

    # Identify apps that should be removed from /system/app/ if they were moved to apk_app
    apps_to_remove_from_system = []
    if os.path.exists(apk_app_dir):
        for f in os.listdir(apk_app_dir):
            if f.lower().endswith(".apk"):
                apps_to_remove_from_system.append(sanitize_app_name(f))

    bash_lines = [
        "set -e",
        "# 1. Ensure loop devices exist in WSL container",
        "mknod /dev/loop-control c 10 237 2>/dev/null || true",
        "for i in 0 1 2 3 4 5 6 7; do mknod /dev/loop$i b 7 $i 2>/dev/null || true; done",
        "",
        "# 2. Mount ext4 system image",
        "mkdir -p /tmp/sysmount",
        "umount /tmp/sysmount 2>/dev/null || true",
        f"mount -o loop,rw '{wsl_raw}' /tmp/sysmount",
        "",
        "# 3. Identify system root (system-as-root vs standard)",
        "SYS='/tmp/sysmount/system'",
        "if [ ! -d \"$SYS/app\" ]; then SYS='/tmp/sysmount'; fi",
        "echo \"Target system path: $SYS\"",
        "",
        "# Clean up legacy unsanitized and duplicate directories in $SYS/app",
        "rm -rf \"$SYS/app/Browser_for_TV_v2.6.3_Premium\" \"$SYS/app/FirefoxTV-4.8.0\" \"$SYS/app/KinoTrend-2.3.8\" 2>/dev/null || true",
        "rm -rf \"$SYS/app/LazyMediaDeluxe_ver3.437\" \"$SYS/app/Media_Station_X_v0.1.163\" \"$SYS/app/NUM_1.0.150-release\" 2>/dev/null || true",
        "rm -rf \"$SYS/app/TorrServe_MatriX.141.Client-release\" \"$SYS/app/WebBrowser_Bro_v1.7.2\" \"$SYS/app/aForkPlayer2.06.9\" 2>/dev/null || true",
        "rm -rf \"$SYS/app/filmixapp-2.2.13\" \"$SYS/app/vlc_2026\" \"$SYS/app/zona_3.0.59\" \"$SYS/app/MX_Player_v2.10.0__2001002860__GP_\" 2>/dev/null || true",
    ]

    # Remove any system app directories for apps now in apk_app
    for app in set(apps_to_remove_from_system):
        bash_lines.append(f"rm -rf \"$SYS/app/{app}\" 2>/dev/null || true")

    bash_lines.extend([
        "",
        "# 4. Copy sanitized extra apps with lib/arm/",
        f"if [ -d '{wsl_staging}' ]; then",
        f"    for appdir in '{wsl_staging}'/*; do",
        "        if [ -d \"$appdir\" ]; then",
        "            appname=$(basename \"$appdir\")",
        "            target=\"$SYS/app/$appname\"",
        "            echo \"  -> Injecting app: $appname into $target\"",
        "            rm -rf \"$target\"",
        "            cp -a \"$appdir\" \"$SYS/app/\"",
        "            find \"$target\" -type d -exec chmod 755 {} +",
        "            find \"$target\" -type f -exec chmod 644 {} +",
        "            chown -R 0:0 \"$target\"",
        "        fi",
        "    done",
        "fi",
        "",
        "# 5. Inject Download-ready APKs and files into /system/etc/apk_app",
        "mkdir -p \"$SYS/etc/apk_app\"",
        "rm -rf \"$SYS/etc/apk_app\"/* \"$SYS/etc/apk_app\"/.* 2>/dev/null || true",
        f"if [ -d '{wsl_staging_apk}' ]; then",
        f"    cp -a '{wsl_staging_apk}'/. \"$SYS/etc/apk_app/\"",
        "    find \"$SYS/etc/apk_app\" -type d -exec chmod 755 {} +",
        "    find \"$SYS/etc/apk_app\" -type f -exec chmod 644 {} +",
        "    chown -R 0:0 \"$SYS/etc/apk_app\"",
        "    echo \"  -> Staged Download folder files in $SYS/etc/apk_app\"",
        "fi",
        "",
        "# 6. Install copy_apk_app boot script and init service",
        "mkdir -p \"$SYS/bin\" \"$SYS/etc/init\"",
        "cat << 'EOF' > \"$SYS/bin/copy_apk_app.sh\"",
        "#!/system/bin/sh",
        "# Automatic copy of APKs and other files to Android Download directory",
        "",
        "SRC=\"/system/etc/apk_app\"",
        "DST=\"/data/media/0/Download\"",
        "MARKER=\"/data/media/0/.apk_app_version\"",
        "",
        "if [ ! -d \"$SRC\" ]; then",
        "    exit 0",
        "fi",
        "",
        "SRC_VER=\"1\"",
        "if [ -f \"$SRC/.version\" ]; then",
        "    SRC_VER=$(cat \"$SRC/.version\" 2>/dev/null)",
        "fi",
        "",
        "if [ -f \"$MARKER\" ]; then",
        "    INSTALLED_VER=$(cat \"$MARKER\" 2>/dev/null)",
        "    if [ \"$INSTALLED_VER\" = \"$SRC_VER\" ]; then",
        "        exit 0",
        "    fi",
        "fi",
        "",
        "# Wait up to 15 seconds for internal storage (/data/media/0)",
        "count=0",
        "while [ ! -d \"/data/media/0\" ] && [ \"$count\" -lt 15 ]; do",
        "    sleep 1",
        "    count=$((count + 1))",
        "done",
        "",
        "if [ ! -d \"/data/media/0\" ]; then",
        "    exit 1",
        "fi",
        "",
        "mkdir -p \"$DST\"",
        "",
        "# Copy all files and folders from $SRC to $DST",
        "for item in \"$SRC\"/*; do",
        "    if [ -e \"$item\" ]; then",
        "        cp -rf \"$item\" \"$DST\"/ 2>/dev/null || true",
        "    fi",
        "done",
        "",
        "# Ensure correct Android media/storage permissions and ownership (media_rw:media_rw = 1023:1023)",
        "chown -R 1023:1023 \"$DST\"",
        "chmod 775 \"$DST\"",
        "find \"$DST\" -type d -exec chmod 775 {} + 2>/dev/null || true",
        "find \"$DST\" -type f -exec chmod 664 {} + 2>/dev/null || true",
        "",
        "# Save completed version marker",
        "echo \"$SRC_VER\" > \"$MARKER\"",
        "chown 1023:1023 \"$MARKER\" 2>/dev/null || true",
        "chmod 664 \"$MARKER\" 2>/dev/null || true",
        "",
        "# Broadcast to Android MediaScanner to immediately index files in Download folder",
        "for f in \"$DST\"/*; do",
        "    if [ -f \"$f\" ]; then",
        "        am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d \"file://$f\" >/dev/null 2>&1 || true",
        "    fi",
        "done",
        "",
        "exit 0",
        "EOF",
        "",
        "chmod 755 \"$SYS/bin/copy_apk_app.sh\"",
        "chown 0:0 \"$SYS/bin/copy_apk_app.sh\"",
        "",
        "cat << 'EOF' > \"$SYS/etc/init/copy_apk_app.rc\"",
        "on property:sys.boot_completed=1",
        "    start copy_apk_app",
        "",
        "on property:dev.bootcomplete=1",
        "    start copy_apk_app",
        "",
        "service copy_apk_app /system/bin/copy_apk_app.sh",
        "    class main",
        "    user root",
        "    group root media_rw sdcard_rw",
        "    disabled",
        "    oneshot",
        "    seclabel u:r:init:s0",
        "EOF",
        "",
        "chmod 644 \"$SYS/etc/init/copy_apk_app.rc\"",
        "chown 0:0 \"$SYS/etc/init/copy_apk_app.rc\"",
        "",
        "# Hook into slim_box_scripts if present",
        "if [ -f \"$SYS/bin/slim_box_scripts\" ]; then",
        "    if ! grep -q \"copy_apk_app.sh\" \"$SYS/bin/slim_box_scripts\"; then",
        "        printf \"\\n/system/bin/copy_apk_app.sh &\\n\" >> \"$SYS/bin/slim_box_scripts\"",
        "    fi",
        "fi",
        "",
    ])

    if wsl_perms:
        bash_lines.extend([
            "# 7. Copy TV / Leanback Permissions",
            f"if [ -d '{wsl_perms}' ]; then",
            "    mkdir -p \"$SYS/etc/permissions\"",
            f"    for xml in '{wsl_perms}'/*.xml; do",
            "        if [ -f \"$xml\" ] && [ -s \"$xml\" ]; then",
            "            echo \"  -> Adding permission: $(basename \"$xml\")\"",
            "            cp -f \"$xml\" \"$SYS/etc/permissions/\"",
            "            chmod 644 \"$SYS/etc/permissions/$(basename \"$xml\")\"",
            "            chown 0:0 \"$SYS/etc/permissions/$(basename \"$xml\")\"",
            "        fi",
            "    done",
            "fi",
            "",
        ])

    if wsl_prop:
        bash_lines.extend([
            "# 8. Update build.prop",
            f"echo \"  -> Updating build.prop from {wsl_prop}\"",
            f"cp -f '{wsl_prop}' \"$SYS/build.prop\"",
            "chmod 644 \"$SYS/build.prop\"",
            "chown 0:0 \"$SYS/build.prop\"",
            "",
        ])

    bash_lines.extend([
        "# 9. Flush and unmount cleanly",
        "sync",
        "umount /tmp/sysmount",
        "echo 'ext4 modification complete and filesystem unmounted successfully.'",
    ])

    full_sh = "\n".join(bash_lines)

    try:
        res = subprocess.run(
            ["wsl", "-u", "root", "-e", "sh", "-c", full_sh],
            capture_output=True,
            text=True,
            check=True
        )
        print(res.stdout)
        if res.stderr:
            print("WSL warnings/stderr:")
            print(res.stderr)
    finally:
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        if os.path.exists(staging_apk_dir):
            shutil.rmtree(staging_apk_dir, ignore_errors=True)

if __name__ == "__main__":
    raw_img = sys.argv[1] if len(sys.argv) > 1 else "system.raw"
    apps = sys.argv[2] if len(sys.argv) > 2 else "extra_apps"
    perms = sys.argv[3] if len(sys.argv) > 3 else "tv_permissions"
    apk_app = sys.argv[4] if len(sys.argv) > 4 else "apk_app"
    modify_system_image(raw_img, apps, perms, apk_app_dir=apk_app)
