import os
import json
import subprocess
import random
import string
from typing import Optional, List, Tuple
import time

def get_removable_drives() -> List[Tuple[str, str]]:
    """Scan for removable drives and return list of (device_id, volume_name) tuples."""
    drives = []
    try:
        volumes = [v for v in os.listdir('/Volumes') 
                  if v not in ['.timemachine', 'Macintosh HD', 'System', 'Home']]
        
        for volume in volumes:
            try:
                info = subprocess.check_output(['diskutil', 'info', f'/Volumes/{volume}'], 
                                            text=True, stderr=subprocess.DEVNULL)
                disk_id = None
                volume_name = volume
                
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
                        continue
                    drives.append((disk_id, volume_name))
                    
            except subprocess.CalledProcessError:
                continue
    except Exception as e:
        print(f"Error scanning drives: {e}")
    
    return drives

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
    # Generate volume name with underscore and 3 random characters
    volume_name = f"{base_name}_{''.join(random.choices(string.ascii_uppercase + string.digits, k=3))}"
    
    print(f"\nPreparing to format drive:")
    print(f"Device: {device_id}")
    print(f"New name: {volume_name}")
    print("\nmeta.json content:")
    print(json.dumps(meta_json, indent=2))
    
    confirm = input("\nProceed with formatting? (Y/n): ")
    if confirm.lower() not in ['y', 'yes', '']:
        return False
    
    try:
        print("\nFormatting drive...")
        # Format with MBR and FAT32
        subprocess.run(['diskutil', 'eraseDisk', 'MS-DOS', volume_name, 'MBR', device_id],
                      check=True, stderr=subprocess.PIPE)
        
        print("Mounting disk...")
        subprocess.run(['diskutil', 'mountDisk', device_id], 
                      check=True, stderr=subprocess.PIPE)
        
        # Small delay to ensure the drive is fully mounted
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

def eject_drive(device_id: str) -> bool:
    """Eject the drive."""
    try:
        subprocess.run(['diskutil', 'eject', device_id], 
                      check=True, stderr=subprocess.PIPE)
        print("Drive ejected successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error ejecting drive: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    # Load meta.json template
    try:
        with open('meta.json', 'r') as f:
            meta_json = json.load(f)
    except Exception as e:
        print(f"Error loading meta.json: {e}")
        return
    
    # Main program loop
    while True:
        print("\nScanning for removable drives...")
        drives = get_removable_drives()
        
        drive = get_drive_selection(drives)
        if drive == 'scan_again':
            continue
        if drive is None:  # User quit
            break
            
        base_name = get_base_name()
        if not base_name:
            continue
            
        if format_drive(drive[0], base_name, meta_json):
            # After successful format, ask about ejecting
            eject_choice = input("\nEject drive now? (Y/n): ")
            if eject_choice.lower() not in ['n', 'no']:
                eject_drive(drive[0])
            
            # Ask about scanning again
            scan_choice = input("\nScan for another drive? (Y/n): ")
            if scan_choice.lower() not in ['y', 'yes', '']:
                break
        else:
            input("\nPress Enter to continue...")

if __name__ == '__main__':
    main()