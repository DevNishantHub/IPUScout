# IPUScout 🔍

An asynchronous service that monitors and automatically downloads exam result PDFs from the GGSIPU (Guru Gobind Singh Indraprastha University) website.

## Features

- 🔍 Automatically scans for new result PDFs on the GGSIPU exam results website
- ⬇️ Downloads results in real-time as they're published
- 🔄 Continuous monitoring with hourly checks for new results
- 📝 Detailed logging of all activities
- 🗃️ Maintains a SQLite database to track downloaded files
- 🧠 Intelligent deduplication to avoid downloading the same content twice
- 📈 Provides download statistics

## Requirements

- Python 3.7 or higher
- Dependencies listed in `requirements.txt`

## Installation

1. Clone this repository or download the script
2. Install required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the script with Python:

```bash
python async_script.py
```

The script will:
1. Perform an initial scan and download of the first 20 result PDFs
2. Display download statistics
3. Enter continuous monitoring mode, checking for new results every hour

To stop the script, press `Ctrl+C` in your terminal.

## Configuration

All downloads are stored in the `ggsipu_results` directory by default. The script also creates:
- A log file (`ggsipu_downloader.log`)
- A SQLite database (`ggsipu_results.db`) to track downloaded PDFs

## Example Output

```
==================================================
GGSIPU PDF Download Summary - Initial Download
==================================================
Initial Downloads: 15 successful, 0 failed, 5 skipped
Total PDFs tracked: 20
Total downloaded: 15
Total size: 45.32 MB
Success rate: 75.0%
==================================================

Starting continuous monitoring for new results...
```
