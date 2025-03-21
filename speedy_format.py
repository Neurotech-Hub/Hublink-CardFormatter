import os
import json
import subprocess
import random
import string
import time
from typing import Optional, List, Tuple
from datetime import datetime
import itertools

# Configuration
TARGET_VOLUME_NAME = "NO NAME"  # The volume name to look for
BASE_NAME = "KEPECS"  # 6-character base name for formatted drives
FORMAT_COUNT = 0  # Keep track of number of drives formatted
SYSTEM_VOLUMES = {'.timemachine', 'Macintosh HD', 'System', 'Home'}  # Cache system volumes

def get_spinner():
    """Returns an iterator for a simple spinner animation."""
    return itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])

def get_target_drive() -> Optional[Tuple[str, str]]:
    """Scan for drive with TARGET_VOLUME_NAME and return (device_id, volume_name) if found."""
    try:
        volumes = set(os.listdir('/Volumes')) - SYSTEM_VOLUMES
        
        if TARGET_VOLUME_NAME in volumes:
            try:
                info = subprocess.check_output(['diskutil', 'info', f'/Volumes/{TARGET_VOLUME_NAME}'], 
                                            text=True, stderr=subprocess.DEVNULL)
                disk_id = None
                
                # Get the whole disk identifier
                for line in info.split('\n'):
                    if 'Part of Whole:' in line:
                        disk_id = f"/dev/{line.split(':')[1].strip()}"
                        break
                
                if disk_id:
                    # Get disk info to verify it's not system disk
                    disk_info = subprocess.check_output(['diskutil', 'info', disk_id],
                                                      text=True, stderr=subprocess.DEVNULL)
                    if 'Internal:' in disk_info and 'Yes' in disk_info.split('Internal:')[1].split('\n')[0]:
                        return None
                    return (disk_id, TARGET_VOLUME_NAME)
                    
            except subprocess.CalledProcessError:
                pass
    except Exception as e:
        print(f"\rError scanning drives: {e}", end='')
    
    return None

def format_drive(device_id: str, meta_json: dict) -> bool:
    """Format drive, set name, and copy meta.json."""
    global FORMAT_COUNT
    
    # Generate volume name with underscore and 3 random characters
    volume_name = f"{BASE_NAME}_{''.join(random.choices(string.ascii_uppercase + string.digits, k=3))}"
    
    try:
        print(f"\rFormatting drive as: {volume_name}...", end='')
        # Format with MBR and FAT32
        subprocess.run(['diskutil', 'eraseDisk', 'MS-DOS', volume_name, 'MBR', device_id],
                      check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        
        print("\rMounting disk...", end='')
        # Mount disk
        subprocess.run(['diskutil', 'mountDisk', device_id], 
                      check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        
        # Reduced delay to ensure the drive is mounted
        time.sleep(1)
        
        print("\rWriting meta.json...", end='')
        # Write meta.json
        with open(f"/Volumes/{volume_name}/meta.json", 'w') as f:
            json.dump(meta_json, f, indent=2)
        
        FORMAT_COUNT += 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\r[{timestamp}] ✓ Drive {FORMAT_COUNT}: {volume_name}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\r❌ Error: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"\r❌ Error: {e}")
        return False

def eject_drive(device_id: str) -> bool:
    """Eject the drive."""
    try:
        print("\rEjecting drive...", end='')
        subprocess.run(['diskutil', 'eject', device_id], 
                      check=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print("\r", end='')  # Clear the ejecting message
        return True
    except subprocess.CalledProcessError as e:
        print(f"\r❌ Error ejecting: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"\r❌ Error: {e}")
        return False

def main():
    # Validate base name configuration
    if len(BASE_NAME) > 6:
        print("Error: BASE_NAME in configuration is too long. Maximum 6 characters.")
        return
    elif len(BASE_NAME) == 0:
        print("Error: BASE_NAME in configuration cannot be empty.")
        return
    
    # Load meta.json template
    try:
        with open('meta.json', 'r') as f:
            meta_json = json.load(f)
    except Exception as e:
        print(f"Error loading meta.json: {e}")
        return
    
    print(f"\nStarting automatic formatting...")
    print(f"Looking for volumes named: {TARGET_VOLUME_NAME}")
    print(f"Using base name: {BASE_NAME}")
    print("Press Ctrl+C to exit\n")
    
    spinner = get_spinner()
    try:
        while True:
            print(f"\r{next(spinner)} Scanning for target volume...", end='')
            drive = get_target_drive()
            
            if drive:
                print("\r", end='')  # Clear the scanning message
                if format_drive(drive[0], meta_json):
                    eject_drive(drive[0])
            
            time.sleep(0.1)  # Reduced scanning interval
            
    except KeyboardInterrupt:
        print("\n\nExiting... Final format count:", FORMAT_COUNT)

if __name__ == '__main__':
    main() 