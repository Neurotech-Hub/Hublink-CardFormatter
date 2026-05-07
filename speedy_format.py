import os
import sys
import json
import subprocess
import random
import string
import time
import platform
from typing import Optional, Tuple, Union, Sequence
from datetime import datetime
import itertools

# Configuration
# Volume label(s) to watch for on removable drives (exact match). Unlabeled FAT32
# often shows as "NO NAME". Use a string or tuple, e.g. ("NO NAME", "KEPECS").
TARGET_VOLUME_NAMES: Union[str, Sequence[str]] = ("NO NAME", "KEPECS")
BASE_NAME = "KEPECS"  # 6-character base name for formatted drives
FORMAT_COUNT = 0      # Keep track of number of drives formatted

# macOS system volumes to ignore during scanning
SYSTEM_VOLUMES = {'.timemachine', 'Macintosh HD', 'System', 'Home'}

IS_WINDOWS = platform.system() == 'Windows'


def _is_windows_admin() -> bool:
    """True if this process has an elevated administrator token (Windows only)."""
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
        "Close this terminal, then open a new one as Administrator:\n"
        "  • Start \"Windows Terminal\" or \"PowerShell\" → right‑click → Run as administrator\n"
        "  • cd to this project folder and run: python speedy_format.py\n",
        file=sys.stderr,
    )


def _target_labels() -> Tuple[str, ...]:
    """Normalize TARGET_VOLUME_NAMES to a tuple of label strings."""
    n = TARGET_VOLUME_NAMES
    if isinstance(n, str):
        return (n,)
    return tuple(n)


def _ps_escape_single(s: str) -> str:
    """Escape a string for use inside single-quoted PowerShell literals."""
    return s.replace("'", "''")


def get_spinner():
    """Returns an iterator for a simple spinner animation."""
    return itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])


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

def _get_target_drive_mac() -> Optional[Tuple[str, str]]:
    try:
        volumes = set(os.listdir('/Volumes')) - SYSTEM_VOLUMES
        for label in _target_labels():
            if label not in volumes:
                continue
            try:
                info = subprocess.check_output(
                    ['diskutil', 'info', f'/Volumes/{label}'],
                    text=True, stderr=subprocess.DEVNULL)
                disk_id = None
                for line in info.split('\n'):
                    if 'Part of Whole:' in line:
                        disk_id = f"/dev/{line.split(':')[1].strip()}"
                        break
                if disk_id:
                    disk_info = subprocess.check_output(
                        ['diskutil', 'info', disk_id],
                        text=True, stderr=subprocess.DEVNULL)
                    if ('Internal:' in disk_info and
                            'Yes' in disk_info.split('Internal:')[1].split('\n')[0]):
                        continue
                    return (disk_id, label)
            except subprocess.CalledProcessError:
                continue
    except Exception as e:
        print(f"\rError scanning drives: {e}", end='')
    return None


def _format_drive_mac(device_id: str, volume_name: str, meta_json: dict) -> bool:
    global FORMAT_COUNT
    try:
        print(f"\rFormatting drive as: {volume_name}...", end='')
        subprocess.run(
            ['diskutil', 'eraseDisk', 'MS-DOS', volume_name, 'MBR', device_id],
            check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print("\rMounting disk...", end='')
        subprocess.run(
            ['diskutil', 'mountDisk', device_id],
            check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        time.sleep(1)
        print("\rWriting meta.json...", end='')
        with open(f"/Volumes/{volume_name}/meta.json", 'w') as f:
            json.dump(meta_json, f, indent=2)
        FORMAT_COUNT += 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\r[{timestamp}] \u2713 Drive {FORMAT_COUNT}: {volume_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\r\u274c Error: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"\r\u274c Error: {e}")
        return False


def _eject_drive_mac(device_id: str) -> bool:
    try:
        print("\rEjecting drive...", end='')
        subprocess.run(
            ['diskutil', 'eject', device_id],
            check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print("\r", end='')
        return True
    except subprocess.CalledProcessError as e:
        print(f"\r\u274c Error ejecting: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"\r\u274c Error: {e}")
        return False


# ──────────────────────────────────────────────────────────────
#  Windows helpers
# ──────────────────────────────────────────────────────────────

def _get_target_drive_windows() -> Optional[Tuple[str, str]]:
    """Find the first portable drive (Removable or USB/SD/MMC bus) whose label matches."""
    try:
        targets = _target_labels()
        ps_array = ",".join(f"'{_ps_escape_single(t)}'" for t in targets)
        # Many SD/USB readers report DriveType Fixed, not Removable — use disk BusType too.
        script = (
            f"$targets = @({ps_array});"
            f"$vol = Get-Volume | Where-Object {{"
            f"  if (-not $_.DriveLetter) {{ return $false }};"
            f"  $part = Get-Partition -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue | Select-Object -First 1;"
            f"  if (-not $part) {{ return $false }};"
            f"  $disk = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue;"
            f"  if (-not $disk) {{ return $false }};"
            f"  if ($disk.IsSystem -or $disk.IsBoot) {{ return $false }};"
            f"  $lbl = if ($_.FileSystemLabel) {{ $_.FileSystemLabel.Trim() }} else {{ 'NO NAME' }};"
            f"  $labelOk = $false; foreach ($t in $targets) {{ if ($lbl -ieq $t) {{ $labelOk = $true; break }} }};"
            f"  if (-not $labelOk) {{ return $false }};"
            f"  if ($_.DriveType -eq 'Removable') {{ return $true }};"
            f"  $bus = [string]$disk.BusType;"
            f"  if (($bus -ieq 'Usb') -or ($bus -ieq 'Sd') -or ($bus -ieq 'Mmc')) {{ return $true }};"
            f"  return $false"
            f"}} | Select-Object -First 1;"
            f"if ($vol -and $vol.DriveLetter) {{"
            f"  $matched = if ($vol.FileSystemLabel) {{ $vol.FileSystemLabel.Trim() }} else {{ 'NO NAME' }};"
            f"  $part = Get-Partition -DriveLetter $vol.DriveLetter -ErrorAction SilentlyContinue | Select-Object -First 1;"
            f"  if ($part) {{ Write-Output ($part.DiskNumber.ToString() + '|' + $matched) }}"
            f"}}"
        )
        result = _run_ps(script, check=False)
        if os.environ.get('SPEEDY_FORMAT_DEBUG', '').lower() in ('1', 'true', 'yes'):
            if result.stderr and result.stderr.strip():
                print(f"\n[debug] PowerShell stderr: {result.stderr.strip()}", file=sys.stderr)
        output = result.stdout.strip()
        if output and '|' in output:
            disk_number, matched_label = output.split('|', 1)
            return (disk_number.strip(), matched_label.strip())
    except Exception as e:
        print(f"\rError scanning drives: {e}", end='')
    return None


def _debug_dump_windows_volumes() -> None:
    """Print volumes visible to PowerShell (set SPEEDY_FORMAT_DEBUG=1)."""
    script = (
        "Get-Volume | Where-Object { $_.DriveLetter } | "
        "Format-Table -AutoSize DriveLetter,@{L='Label';E={$_.FileSystemLabel}},"
        "DriveType,@{L='SizeGB';E={[math]::Round($_.Size/1GB,2)}} | Out-String -Width 220"
    )
    r = _run_ps(script, check=False)
    print("\n[debug] Get-Volume (lettered volumes):\n", r.stdout or r.stderr, file=sys.stderr)
    script2 = (
        "Get-Disk | Where-Object { -not $_.IsSystem } | "
        "Format-Table -AutoSize Number,BusType,IsBoot,Size,FriendlyName | Out-String -Width 220"
    )
    r2 = _run_ps(script2, check=False)
    print("[debug] Get-Disk (non-system):\n", r2.stdout or r2.stderr, file=sys.stderr)


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
    global FORMAT_COUNT
    # FAT32 volume labels are limited to 11 characters
    label = volume_name[:11]
    try:
        print(f"\rFormatting drive as: {volume_name}...", end='')
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
            print("\r\u274c Error: Could not determine drive letter after formatting.")
            return False
        print("\rWriting meta.json...", end='')
        time.sleep(1)
        mount_path = f"{drive_letter}:\\"
        with open(os.path.join(mount_path, 'meta.json'), 'w') as f:
            json.dump(meta_json, f, indent=2)
        FORMAT_COUNT += 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\r[{timestamp}] \u2713 Drive {FORMAT_COUNT}: {volume_name}")
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr or ''
        print(f"\r\u274c Error: {err}")
        if _windows_storage_denied(err):
            _print_windows_admin_format_help()
        return False
    except Exception as e:
        print(f"\r\u274c Error: {e}")
        return False


def _eject_drive_windows(disk_number: str) -> bool:
    drive_letter = _get_drive_letter_for_disk_windows(disk_number)
    if not drive_letter:
        print("\r\u274c Could not locate drive letter; please eject manually.")
        return False
    try:
        eject_script = (
            f"$shell = New-Object -ComObject Shell.Application;"
            f"$folder = $shell.Namespace(17).ParseName('{drive_letter}:');"
            f"if ($folder) {{ $folder.InvokeVerb('Eject') }} else {{ exit 1 }}"
        )
        _run_ps(eject_script)
        print("\r", end='')
        return True
    except subprocess.CalledProcessError as e:
        print(f"\r\u274c Error ejecting: {e.stderr}")
        return False
    except Exception as e:
        print(f"\r\u274c Error: {e}")
        return False


# ──────────────────────────────────────────────────────────────
#  Public API  (OS-routing wrappers)
# ──────────────────────────────────────────────────────────────

def get_target_drive() -> Optional[Tuple[str, str]]:
    """Scan for a removable drive whose label matches TARGET_VOLUME_NAMES; return (device_id, matched_label) or None."""
    if IS_WINDOWS:
        return _get_target_drive_windows()
    return _get_target_drive_mac()


def format_drive(device_id: str, meta_json: dict) -> bool:
    """Format drive, set name, and copy meta.json."""
    volume_name = f"{BASE_NAME}_{''.join(random.choices(string.ascii_uppercase + string.digits, k=3))}"
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
    if len(BASE_NAME) > 6:
        print("Error: BASE_NAME in configuration is too long. Maximum 6 characters.")
        return
    elif len(BASE_NAME) == 0:
        print("Error: BASE_NAME in configuration cannot be empty.")
        return

    try:
        with open('meta.json', 'r') as f:
            meta_json = json.load(f)
    except Exception as e:
        print(f"Error loading meta.json: {e}")
        return

    if IS_WINDOWS:
        if not _is_windows_admin():
            print(
                "Error: This script is not running as Administrator; disk erase will fail on Windows.",
                file=sys.stderr,
            )
            _print_windows_admin_format_help()
            sys.exit(1)
        print(
            "SD/USB media often shows as Fixed (not Removable); scanning includes USB/SD/MMC buses."
        )
        if os.environ.get('SPEEDY_FORMAT_DEBUG', '').lower() in ('1', 'true', 'yes'):
            _debug_dump_windows_volumes()

    print(f"\nStarting automatic formatting...")
    print(f"Looking for volume label(s): {', '.join(_target_labels())}")
    print(f"Using base name: {BASE_NAME}")
    print("Press Ctrl+C to exit\n")

    spinner = get_spinner()
    try:
        while True:
            print(f"\r{next(spinner)} Scanning for target volume...", end='')
            drive = get_target_drive()
            if drive:
                print("\r", end='')
                if format_drive(drive[0], meta_json):
                    eject_drive(drive[0])
            # Windows: spawning PowerShell each loop is slow; a slightly longer pause is fine.
            time.sleep(0.5 if IS_WINDOWS else 0.1)
    except KeyboardInterrupt:
        print("\n\nExiting... Final format count:", FORMAT_COUNT)


if __name__ == '__main__':
    main()
