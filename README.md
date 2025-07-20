# GGSIPU Results Monitor & Downloader

Automatically monitors and downloads exam result PDFs from GGSIPU website with 24-hour auto-cleanup and smart resume functionality.

## Features

- **Auto-Monitoring**: Continuously checks for new exam results
- **Smart Detection**: MD5 hashing to detect new PDFs
- **Auto-Cleanup**: Deletes PDFs exactly 24 hours after download
- **Smart Resume**: Automatically continues from where you left off
- **Keyword Filtering**: Filter downloads by any custom keyword (even single letters)
- **Multiple Modes**: Monitor, download-all, test, status, cleanup-only
- **Organized Storage**: JSON metadata files stored separately from PDFs

## UV Package Manager

This project uses [UV](https://docs.astral.sh/uv/) - a fast Python package manager written in Rust. UV provides faster dependency resolution and installation compared to pip.

**Installation:** Visit [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/) for complete installation instructions for your operating system.

**Quick install commands:**
- **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS/Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Quick Start

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Start monitoring**:
   ```bash
   python ggsipu_downloader.py --monitor
   ```

## Usage

### Basic Commands

```bash
# Start monitoring (5-minute intervals) - resumes automatically
python ggsipu_downloader.py --monitor

# Start monitoring with custom interval (10 minutes)
python ggsipu_downloader.py --monitor 10

# Start monitoring with keyword filter
python ggsipu_downloader.py --monitor --keyword="mba"

# Download all current results
python ggsipu_downloader.py --download-all

# Download only PDFs matching a keyword
python ggsipu_downloader.py --download-all --keyword="btech"

# Download with single letter filter
python ggsipu_downloader.py --download-all --keyword="m"

# Check once for new results
python ggsipu_downloader.py --check-once
```
### Keyword Filtering

The `--keyword` parameter allows you to **filter which PDFs get downloaded**:

| Command | What It Downloads |
|---------|-------------------|
| `--keyword="mba"` | Only PDFs with "mba" in filename or title |
| `--keyword="btech"` | Only PDFs with "btech" in filename or title |
| `--keyword="2025"` | Only PDFs with "2025" in filename or title |
| `--keyword="june"` | Only PDFs with "june" in filename or title |
| `--keyword="m"` | Only PDFs with letter "m" in filename or title |
| `--keyword="result"` | Only PDFs with "result" in filename or title |

**Keyword Filtering Rules:**
- ✅ **Case insensitive**: "--keyword=MBA" matches "mba", "MBA", "Mba"
- ✅ **Partial matches**: "--keyword=tech" finds "BTech_Results.pdf"
- ✅ **Any length**: Single letters work: "--keyword=m" 
- ✅ **Filename + Title**: Searches both PDF filename and link text
- ✅ **Exact substring**: Must be exact match within the text

## How It Works

### Automatic Resume Feature

1. **First Run**: Downloads PDFs and saves the latest one to `latest_result.json`
2. **Subsequent Runs**: Automatically resumes from the last processed PDF
3. **Manual Override**: Use `--start-from` to start from a different point
4. **Smart Tracking**: Always remembers the most recent PDF processed

### Example Resume Workflow

```bash
# Day 1: Start monitoring
python ggsipu_downloader.py --monitor
# Downloads: MBA_June2025.pdf, BTech_July2025.pdf
# Saves: BTech_July2025.pdf as latest result

# Day 2: Restart monitoring (automatic resume)
python ggsipu_downloader.py --monitor
# Automatically starts checking after BTech_July2025.pdf
# Only downloads newer PDFs

# Manual restart with keyword filter
python ggsipu_downloader.py --monitor --keyword="mba"
# Only monitors and downloads MBA-related PDFs
```

## File Structure

```
ggsipu_results/
├── metadata/                   # JSON tracking files (NEW!)
│   ├── download_metadata.json  # Tracks downloaded files and expiration times
│   ├── monitoring_data.json    # Stores monitoring statistics and known PDFs
│   └── latest_result.json      # Tracks the most recent PDF processed
└── [downloaded PDFs]           # Actual PDF files (auto-deleted after 24 hours)
```

### Latest Result Tracking

The `latest_result.json` file contains:
```json
{
  "filename": "M.Ed_Result_2nd_Sem_July_2025.pdf",
  "title": "Exam (July 2025) Result for M.Ed, 2nd Sem",
  "url": "http://ggsipu.ac.in/ExamResults/2025/...",
  "timestamp": "2025-07-17T15:14:40.800212",
  "position": 0,
  "date_source": "http_header"
}
```

## Advanced Usage

### Reset Tracking
```bash
# Delete tracking file to start fresh
del ggsipu_results\metadata\latest_result.json
python ggsipu_downloader.py --monitor
```

### Check Current State
```bash
# See what's currently tracked as latest
python ggsipu_downloader.py --status
```

### Common Use Cases

**Scenario 1: Daily Monitoring**
```bash
# Set up once, runs automatically
python ggsipu_downloader.py --monitor
# Always resumes from last processed PDF
```

**Scenario 2: Download All Results with Filter**
```bash
# Download all current PDFs but only BTech ones
python ggsipu_downloader.py --download-all --keyword="btech"
```

**Scenario 3: Monitor Specific Program Only**
```bash
# Only monitor and download MBA results
python ggsipu_downloader.py --monitor --keyword="mba"
```

**Scenario 4: Single Letter Filtering**
```bash
# Download all PDFs containing letter "m"
python ggsipu_downloader.py --download-all --keyword="m"
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
