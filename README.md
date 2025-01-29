# Hublink Drive Formatter

A macOS-only command-line tool for safely formatting removable media devices for use with [hublink.cloud](https://hublink.cloud).

## Features

- Safe detection of removable media only (no system drives)
- FAT32 formatting using macOS diskutil
- Automatic configuration file creation
- Interactive terminal interface
- Safe drive ejection via diskutil

## Requirements

- Python 3.6 or higher
- macOS only (relies on diskutil commands)

## Installation

1. Clone this repository:
```bash
git clone [repository-url]
cd HublinkJsonFormatter
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

## Files

- `format_meta_json.py` - For formatting Hublink Node drives (requires meta.json template)
- `format_hublink_config.py` - For formatting Hublink Gateway drives
- `meta.json` - Configuration template for Nodes
- `README.md` - Documentation
- `.gitignore` - Git ignore rules

## Usage

### For Hublink Nodes

1. Ensure meta.json is configured with your desired settings
2. Run: `python format_meta_json.py`
3. Follow the prompts to:
   - Select a drive
   - Enter a 6-character base name
   - Confirm and format

### For Hublink Gateways

1. Run: `python format_hublink_config.py`
2. Follow the prompts to:
   - Select a drive
   - Enter the Hublink secret URL
   - Enter the gateway name
   - Confirm and format

## Safety Features

- Only detects and lists removable drives
- Excludes system drives and internal disks
- Confirmation required before formatting
- Clear error messages
- Option to quit at any step
- Safe drive ejection
- Proper mount/unmount handling

## Note

Administrative privileges may be required for formatting operations. 