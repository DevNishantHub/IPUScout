# GGSIPU Exam Results PDF Downloader

An asynchronous service that monitors and downloads exam result PDFs from Guru Gobind Singh Indraprastha University (GGSIPU) website.

## Features

- **Automatic Monitoring**: Periodically checks for new result PDFs
- **Efficient Downloads**: Uses asynchronous operations for better performance
- **Smart Detection**: Uses BeautifulSoup for reliable HTML parsing
- **Duplicate Prevention**: Uses content hashing to prevent duplicate downloads
- **Database Tracking**: Stores file metadata in SQLite database
- **Logging**: Comprehensive logging of all operations

## Requirements

- Python 3.7 or higher
- Dependencies listed in `requirements.txt`

## Installation

1. Clone this repository
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the script to start monitoring:

```bash
python async_script.py
```

The script will:

1. Perform an initial download of the most recent result PDFs
2. Continue monitoring for new PDFs every hour
3. Log all activity to `ggsipu_downloader.log`
4. Store downloaded PDFs in the `ggsipu_results` directory

## Configuration

You can modify the following parameters in the script:

- `base_url`: The main URL to monitor
- `download_dir`: Directory where PDFs will be stored
- `db_path`: Path to SQLite database file

## License

This project is open source and available under the MIT License.
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
