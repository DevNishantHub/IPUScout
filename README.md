# GGSIPU Results Monitor & Downloader

Automatically monitors and downloads exam result PDFs from GGSIPU website with 24-hour auto-cleanup.

## Features

- **Auto-Monitoring**: Continuously checks for new exam results
- **Smart Detection**: MD5 hashing to detect new PDFs
- **Auto-Cleanup**: Deletes PDFs exactly 24 hours after download
- **Multiple Modes**: Monitor, download-all, test, status, cleanup-only

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start monitoring**:
   ```bash
   python ggsipu_downloader.py --monitor
   ```

## Usage

```bash
# Start monitoring (5-minute intervals)
python ggsipu_downloader.py --monitor

# Download all current results
python ggsipu_downloader.py --download-all

# Check once for new results
python ggsipu_downloader.py --check-once

# Test system components
python ggsipu_downloader.py --test

# Show current status
python ggsipu_downloader.py --status
```

## How It Works

1. Monitors GGSIPU website every 5 minutes
2. Downloads new PDFs when detected
3. Auto-deletes files after 24 hours
4. Tracks everything in JSON metadata files

## File Structure

```
ggsipu_results/
├── download_metadata.json    # Download tracking
├── monitoring_data.json      # Monitoring stats
└── [PDFs]                   # Auto-deleted after 24h
```

## Requirements

- Python 3.7+
- Internet connection
- ~50MB disk space

## Dependencies

- `aiohttp` - Async HTTP requests
- `aiofiles` - Async file operations
- `beautifulsoup4` - HTML parsing
- `lxml` - XML/HTML parser

## Author

**DevNishantHub** - [GitHub](https://github.com/DevNishantHub) | [IPUScout](https://github.com/DevNishantHub/IPUScout)
