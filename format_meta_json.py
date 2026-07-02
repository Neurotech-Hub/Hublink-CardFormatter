import os
import sys
import json
import subprocess
import random
import string
import platform
from typing import Optional, List, Tuple
import time

IS_WINDOWS = platform.system() == 'Windows'


def _is_windows_admin() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _windows_storage_denied(stderr: str) -> bool:
    if not stderr:
        return False
    s = stderr.lower()
    return (
        'cleardisk' in s.replace('-', '')
        or 'permissiondenied' in s.replace(' ', '')
        or 'cim resource' in s
        or 'access to a cim resource' in s
        or 'not available to the client' in s
    )


def _print_windows_admin_format_help() -> None:
    print(
        "\nClear-Disk / Format-Volume need Administrator rights on Windows.\n"
        "Right‑click Terminal or PowerShell → Run as administrator, cd to this folder, then:\n"
        "  python format_meta_json.py\n",
        file=sys.stderr,
    )


# ──────────────────────────────────────────────────────────────
#  Shared PowerShell runner (Windows only)
# ──────────────────────────────────────────────────────────────

def _run_ps(script: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a PowerShell one-liner and return the CompletedProcess."""
    return subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=check,
    )


# ──────────────────────────────────────────────────────────────
#  macOS helpers
# ──────────────────────────────────────────────────────────────

def _get_removable_drives_mac() -> List[Tuple[str, str]]:
    drives = []
    try:
        # Exclude system volumes, recovery volumes, and Time Machine backups
        excluded_volumes = ['.timemachine', 'Macintosh HD', 'System', 'Home', 'Recovery']
        volumes = [v for v in os.listdir('/Volumes')
                   if not any(excluded in v for excluded in excluded_volumes)]

        for volume in volumes:
            try:
                info = subprocess.check_output(
                    ['diskutil', 'info', f'/Volumes/{volume}'],
                    text=True, stderr=subprocess.DEVNULL)
                disk_id = None
                volume_name = volume

                # Skip if this appears to be a recovery partition
                if 'Recovery' in info or 'Apple_Boot' in info:
                    continue

                for line in info.split('\n'):
                    if 'Part of Whole:' in line:
                        disk_id = f"/dev/{line.split(':')[1].strip()}"
                        break
                if disk_id:
                    disk_info = subprocess.check_output(
                        ['diskutil', 'info', disk_id],
                        text=True, stderr=subprocess.DEVNULL)

                    # Skip internal drives and recovery partitions
                    if ('Internal:' in disk_info and
                            'Yes' in disk_info.split('Internal:')[1].split('\n')[0]):
                        continue

                    if 'Recovery' in disk_info or 'Recovery' in volume_name:
                        continue

                    drives.append((disk_id, volume_name))
            except subprocess.CalledProcessError:
                continue
    except Exception as e:
        print(f"Error scanning drives: {e}")
    return drives


def _format_drive_mac(device_id: str, volume_name: str, meta_json: dict) -> bool:
    try:
        print("\nFormatting drive...")
        subprocess.run(
            ['diskutil', 'eraseDisk', 'MS-DOS', volume_name, 'MBR', device_id],
            check=True, stderr=subprocess.PIPE)
        print("Mounting disk...")
        subprocess.run(
            ['diskutil', 'mountDisk', device_id],
            check=True, stderr=subprocess.PIPE)
        time.sleep(2)
        print("Writing meta.json...")
        with open(f"/Volumes/{volume_name}/meta.json", 'w') as f:
            json.dump(meta_json, f, indent=2)
        print("\nDrive formatted successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\nError: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def _eject_drive_mac(device_id: str) -> bool:
    try:
        subprocess.run(
            ['diskutil', 'eject', device_id],
            check=True, stderr=subprocess.PIPE)
        print("Drive ejected successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error ejecting drive: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


# ──────────────────────────────────────────────────────────────
#  Windows helpers
# ──────────────────────────────────────────────────────────────

def _get_removable_drives_windows() -> List[Tuple[str, str]]:
    """Return list of (disk_number_str, 'X: Label') for portable volumes (not only DriveType Removable)."""
    drives = []
    try:
        # SD/USB readers often report Fixed + USB/SD/MMC rather than Removable.
        script = (
            "Get-Volume | Where-Object {"
            "  if (-not $_.DriveLetter) { return $false };"
            "  $part = Get-Partition -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue | Select-Object -First 1;"
            "  if (-not $part) { return $false };"
            "  $disk = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue;"
            "  if (-not $disk) { return $false };"
            "  if ($disk.IsSystem -or $disk.IsBoot) { return $false };"
            "  if ($_.DriveType -eq 'Removable') { return $true };"
            "  $bus = [string]$disk.BusType;"
            "  if (($bus -ieq 'Usb') -or ($bus -ieq 'Sd') -or ($bus -ieq 'Mmc')) { return $true };"
            "  return $false"
            "} | ForEach-Object {"
            "  $dl = $_.DriveLetter;"
            "  $label = if ($_.FileSystemLabel) { $_.FileSystemLabel.Trim() } else { 'NO NAME' };"
            "  $part = Get-Partition -DriveLetter $dl -ErrorAction SilentlyContinue | Select-Object -First 1;"
            "  if ($part) { \"$($part.DiskNumber)|$dl|$label\" }"
            "}"
        )
        result = _run_ps(script, check=False)
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.count('|') >= 2:
                disk_num, drive_letter, label = line.split('|', 2)
                display = f"{drive_letter.strip()}: {label.strip()}"
                drives.append((disk_num.strip(), display))
    except Exception as e:
        print(f"Error scanning drives: {e}")
    return drives


def _get_drive_letter_for_disk_windows(disk_number: str) -> Optional[str]:
    """Return the first drive letter assigned to a disk number, or None."""
    try:
        script = (
            f"Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue | "
            f"Where-Object {{$_.DriveLetter -match '[A-Z]'}} | "
            f"Select-Object -First 1 -ExpandProperty DriveLetter"
        )
        result = _run_ps(script, check=False)
        letter = result.stdout.strip()
        return letter if letter else None
    except Exception:
        return None


def _format_drive_windows(disk_number: str, volume_name: str, meta_json: dict) -> bool:
    # FAT32 volume labels are limited to 11 characters
    label = volume_name[:11]
    if not _is_windows_admin():
        print(
            "\nError: This terminal is not running as Administrator; "
            "Windows blocks Clear-Disk / format without elevation."
        )
        _print_windows_admin_format_help()
        return False
    try:
        print("\nFormatting drive...")
        format_script = (
            f"$ErrorActionPreference = 'Stop';"
            f"$disk = Get-Disk -Number {disk_number};"
            f"$disk | Clear-Disk -RemoveData -RemoveOEM -Confirm:$false;"
            f"$disk | Initialize-Disk -PartitionStyle MBR -Confirm:$false -ErrorAction SilentlyContinue;"
            f"$part = $disk | New-Partition -UseMaximumSize -AssignDriveLetter;"
            f"$part | Format-Volume -FileSystem FAT32 -NewFileSystemLabel '{label}' -Confirm:$false | Out-Null;"
            f"$part.DriveLetter"
        )
        result = _run_ps(format_script)
        drive_letter = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ''
        if not drive_letter:
            print("\nError: Could not determine drive letter after formatting.")
            return False
        time.sleep(1)
        print("Writing meta.json...")
        mount_path = f"{drive_letter}:\\"
        with open(os.path.join(mount_path, 'meta.json'), 'w') as f:
            json.dump(meta_json, f, indent=2)
        print("\nDrive formatted successfully!")
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr or ''
        print(f"\nError: {err}")
        if _windows_storage_denied(err):
            _print_windows_admin_format_help()
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def _eject_drive_windows(disk_number: str) -> bool:
    drive_letter = _get_drive_letter_for_disk_windows(disk_number)
    if not drive_letter:
        print("Could not locate drive letter for ejection; please eject manually.")
        return False
    try:
        eject_script = (
            f"$shell = New-Object -ComObject Shell.Application;"
            f"$folder = $shell.Namespace(17).ParseName('{drive_letter}:');"
            f"if ($folder) {{ $folder.InvokeVerb('Eject') }} else {{ exit 1 }}"
        )
        _run_ps(eject_script)
        print("Drive ejected successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error ejecting drive: {e.stderr}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


# ──────────────────────────────────────────────────────────────
#  Public API  (OS-routing wrappers)
# ──────────────────────────────────────────────────────────────

def get_removable_drives() -> List[Tuple[str, str]]:
    """Scan for removable drives; return list of (device_id, volume_display)."""
    if IS_WINDOWS:
        return _get_removable_drives_windows()
    return _get_removable_drives_mac()


def get_drive_selection(drives: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """Present drive selection menu and return selected (device_id, volume_name)."""
    if not drives:
        print("\nNo removable drives found.")
        scan_again = input("\nScan again? (Y/n): ")
        if scan_again.lower() in ['n', 'no']:
            return None
        return 'scan_again'

    print("\nAvailable drives:")
    for i, (disk_id, volume) in enumerate(drives, 1):
        print(f"{i}. {disk_id} - {volume}")

    while True:
        try:
            choice = input("\nSelect drive number (or 'q' to quit): ")
            if choice.lower() == 'q':
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(drives):
                return drives[idx]
            print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a number or 'q' to quit.")


def get_base_name() -> Optional[str]:
    """Get 6-character base name from user."""
    while True:
        name = input("\nEnter 6-character base name (or 'q' to quit): ").upper()
        if name.lower() == 'q':
            return None
        if len(name) > 6:
            print("Name too long. Maximum 6 characters.")
        elif len(name) == 0:
            print("Please enter a name.")
        else:
            return name


def format_drive(device_id: str, base_name: str, meta_json: dict) -> bool:
    """Format drive, set name, and copy meta.json."""
    volume_name = f"{base_name}_{''.join(random.choices(string.ascii_uppercase + string.digits, k=3))}"

    print(f"\nPreparing to format drive:")
    print(f"Device: {device_id}")
    print(f"New name: {volume_name}")
    print("\nmeta.json content:")
    print(json.dumps(meta_json, indent=2))

    confirm = input("\nProceed with formatting? (Y/n): ")
    if confirm.lower() not in ['y', 'yes', '']:
        return False

    if IS_WINDOWS:
        return _format_drive_windows(device_id, volume_name, meta_json)
    return _format_drive_mac(device_id, volume_name, meta_json)


def eject_drive(device_id: str) -> bool:
    """Eject the drive."""
    if IS_WINDOWS:
        return _eject_drive_windows(device_id)
    return _eject_drive_mac(device_id)


# ──────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────

def main():
    if IS_WINDOWS:
        if not _is_windows_admin():
            print(
                "Warning: not running as Administrator — listing drives may work, "
                "but formatting will fail until you open an elevated terminal.\n"
            )
        else:
            print("Running with Administrator privileges (required for Windows formatting).\n")
    try:
        with open('meta.json', 'r') as f:
            meta_json = json.load(f)
    except Exception as e:
        print(f"Error loading meta.json: {e}")
        return

    while True:
        print("\nScanning for removable drives...")
        drives = get_removable_drives()

        drive = get_drive_selection(drives)
        if drive == 'scan_again':
            continue
        if drive is None:
            break

        base_name = get_base_name()
        if not base_name:
            continue

        if format_drive(drive[0], base_name, meta_json):
            eject_choice = input("\nEject drive now? (Y/n): ")
            if eject_choice.lower() not in ['n', 'no']:
                eject_drive(drive[0])

            scan_choice = input("\nScan for another drive? (Y/n): ")
            if scan_choice.lower() not in ['y', 'yes', '']:
                break
        else:
            input("\nPress Enter to continue...")


if __name__ == '__main__':
    main()
