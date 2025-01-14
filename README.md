# Drive Formatter

A macOS-only command-line tool for safely formatting removable media devices. Formats drives to FAT32 and automatically adds a configured meta.json file.

## Features

- Safe detection of removable media only (no system drives)
- FAT32 formatting using macOS diskutil
- Custom volume naming (6 letters + underscore + 3 random alphanumeric)
- Automatic meta.json file creation
- Interactive terminal interface
- Safe drive ejection via diskutil

## Requirements

- Python 3.6 or higher
- macOS only (relies on diskutil commands)

## Installation

1. Clone this repository:
```bash
git clone [repository-url]
cd MetaJsonFormatter
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

## Usage

1. Ensure meta.json is configured with your desired settings

2. Run the script:
```bash
python format_drive.py
```

3. The program will:
   - Scan and list available removable drives
   - Prompt you to select a drive by number
   - Ask for a 6-character base name
   - Show formatting details for confirmation
   - Format the drive and add meta.json
   - Offer to eject the drive
   - Ask if you want to format another drive

Example session:
```
Scanning for removable drives...

Available drives:
1. /dev/disk9 - NO NAME

Select drive number (or 'q' to quit): 1

Enter 6-character base name (or 'q' to quit): MOUSE1

Preparing to format drive:
Device: /dev/disk9
New name: MOUSE1_X2Y

meta.json content:
{
  "hublink": {
    ...
  }
}

Proceed with formatting? (Y/n): Y

Formatting drive...
Mounting disk...
Writing meta.json...
Drive formatted successfully!

Eject drive now? (Y/n): Y
Drive ejected successfully!

Scan for another drive? (Y/n):
```

## Safety Features

- Only detects and lists removable drives
- Excludes system drives and internal disks
- Confirmation required before formatting
- Clear error messages
- Option to quit at any step
- Safe drive ejection
- Proper mount/unmount handling

## File Structure

- `format_drive.py` - Main program
- `meta.json` - Configuration template
- `README.md` - Documentation
- `.gitignore` - Git ignore rules

## Note

Administrative privileges may be required for formatting operations. 