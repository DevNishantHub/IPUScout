#!/usr/bin/env python3
"""
GGSIPU Exam Results PDF Download Service
Async script to monitor and download recent exam result PDFs from GGSIPU website
"""

import asyncio
import aiohttp
import aiofiles
import json
import re
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass
import sqlite3
import time
from bs4 import BeautifulSoup  # Added BeautifulSoup import

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ggsipu_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class PDFResult:
    """Data class for PDF result information"""
    url: str
    filename: str
    title: str
    date_found: datetime
    file_size: Optional[int] = None
    hash_md5: Optional[str] = None
    downloaded: bool = False
    download_path: Optional[str] = None

class GGSIPUDownloader:
    """Async service to download GGSIPU exam result PDFs"""
    
    def __init__(self, 
                 base_url: str = "http://ggsipu.ac.in/ExamResults/ExamResultsmain.htm",
                 download_dir: str = "ggsipu_results",
                 db_path: str = "ggsipu_results.db"):
        self.base_url = base_url
        self.download_dir = Path(download_dir)
        self.db_path = db_path
        self.session: Optional[aiohttp.ClientSession] = None
        self.known_pdfs: Set[str] = set()
        
        # Create download directory
        self.download_dir.mkdir(exist_ok=True)
        
        # Initialize database
        self._init_database()
        
    def _init_database(self):
        """Initialize SQLite database for tracking PDFs"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pdf_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                title TEXT,
                date_found TEXT NOT NULL,
                file_size INTEGER,
                hash_md5 TEXT,
                downloaded BOOLEAN DEFAULT FALSE,
                download_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
    async def __aenter__(self):
        """Async context manager entry"""
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
            
    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch webpage content"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    logger.info(f"Successfully fetched page: {url}")
                    return content
                else:
                    logger.warning(f"Failed to fetch {url}: Status {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None
            
    async def extract_pdf_links(self, html_content: str, base_url: str) -> List[PDFResult]:
        """Extract PDF links from HTML content using BeautifulSoup"""
        pdf_results = []
        
        # Parse the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all links (a tags)
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Check if link points to a PDF file
            if href.lower().endswith('.pdf'):
                # Clean and normalize URL
                pdf_url = urljoin(base_url, href)
                
                # Extract filename
                filename = Path(urlparse(pdf_url).path).name
                if not filename:
                    continue
                
                # Extract title from the link text or surrounding context
                title = self._extract_title_from_link(link)
                
                pdf_result = PDFResult(
                    url=pdf_url,
                    filename=filename,
                    title=title,
                    date_found=datetime.now()
                )
                
                pdf_results.append(pdf_result)
        
        return pdf_results
        
    def _extract_title_from_link(self, link_tag) -> str:
        """Extract title from BeautifulSoup link tag"""
        # First try to use the link text itself
        if link_tag.string and link_tag.string.strip():
            return link_tag.string.strip()
        
        # If link has no text but contains another tag (like an image)
        if link_tag.find('img') and link_tag.find('img').get('alt'):
            return link_tag.find('img').get('alt').strip()
            
        # Try to get text from parent paragraph or list item
        parent = link_tag.find_parent(['p', 'li', 'td', 'div'])
        if parent and parent.get_text().strip():
            # Get a cleaned version of the parent text
            text = parent.get_text().strip()
            # Limit to reasonable length
            if len(text) > 100:
                text = text[:100] + '...'
            return text
            
        # Fall back to the filename
        filename = Path(link_tag['href']).stem
        return filename.replace('_', ' ').replace('-', ' ').title()
        
    def _extract_additional_result_urls(self, html_content: str) -> List[str]:
        """Extract additional result page URLs using BeautifulSoup"""
        urls = []
        
        # Parse the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all links
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Check if the link points to an HTML page with 'result' in the name
            if (href.lower().endswith('.htm') or href.lower().endswith('.html')) and \
               ('result' in href.lower() or 'exam' in href.lower()):
                full_url = urljoin(self.base_url, href)
                if full_url not in urls and full_url != self.base_url:
                    urls.append(full_url)
                    
        return urls[:10]  # Limit to avoid excessive requests
        
    async def download_pdf(self, pdf_result: PDFResult) -> Tuple[bool, bool]:
        """Download a single PDF file
        Returns: (success, skipped) tuple
        """
        try:
            # Check if already downloaded
            if self._is_pdf_downloaded(pdf_result.url):
                logger.info(f"PDF already downloaded: {pdf_result.filename}")
                return True, True  # Success but skipped
                
            # Create safe filename
            safe_filename = self._create_safe_filename(pdf_result.filename)
            download_path = self.download_dir / safe_filename
            
            # Download the PDF
            async with self.session.get(pdf_result.url) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Calculate hash
                    hash_md5 = hashlib.md5(content).hexdigest()
                    
                    # Check if we already have this content
                    if self._is_content_duplicate(hash_md5):
                        logger.info(f"Duplicate content found for: {pdf_result.filename}")
                        return False, True  # Not success but skipped
                    
                    # Save the file
                    async with aiofiles.open(download_path, 'wb') as f:
                        await f.write(content)
                    
                    # Update PDF result
                    pdf_result.file_size = len(content)
                    pdf_result.hash_md5 = hash_md5
                    pdf_result.downloaded = True
                    pdf_result.download_path = str(download_path)
                    
                    # Save to database
                    self._save_pdf_to_db(pdf_result)
                    
                    logger.info(f"Successfully downloaded: {pdf_result.filename} ({len(content)} bytes)")
                    return True, False  # Success and not skipped
                else:
                    logger.error(f"Failed to download {pdf_result.url}: Status {response.status}")
                    return False, False  # Not success and not skipped
                    
        except Exception as e:
            logger.error(f"Error downloading {pdf_result.url}: {str(e)}")
            return False, False  # Not success and not skipped
            
    def _create_safe_filename(self, filename: str) -> str:
        """Create a safe filename for the filesystem"""
        # Remove invalid characters
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # Add timestamp if file exists
        counter = 1
        base_name = Path(safe_filename).stem
        extension = Path(safe_filename).suffix
        
        while (self.download_dir / safe_filename).exists():
            safe_filename = f"{base_name}_{counter}{extension}"
            counter += 1
            
        return safe_filename
        
    def _is_pdf_downloaded(self, url: str) -> bool:
        """Check if PDF is already downloaded"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM pdf_results WHERE url = ? AND downloaded = TRUE", (url,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
        
    def _is_content_duplicate(self, hash_md5: str) -> bool:
        """Check if content is duplicate based on hash"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM pdf_results WHERE hash_md5 = ?", (hash_md5,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
        
    def _save_pdf_to_db(self, pdf_result: PDFResult):
        """Save PDF result to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO pdf_results 
            (url, filename, title, date_found, file_size, hash_md5, downloaded, download_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pdf_result.url,
            pdf_result.filename,
            pdf_result.title,
            pdf_result.date_found.isoformat(),
            pdf_result.file_size,
            pdf_result.hash_md5,
            pdf_result.downloaded,
            pdf_result.download_path
        ))
        
        conn.commit()
        conn.close()
        
    async def scan_for_new_pdfs(self) -> List[PDFResult]:
        """Scan the main results page for new PDFs"""
        logger.info("Scanning for new PDFs...")
        
        # Fetch main page
        html_content = await self.fetch_page(self.base_url)
        if not html_content:
            logger.error("Failed to fetch main results page")
            return []
            
        # Extract PDF links
        pdf_results = await self.extract_pdf_links(html_content, self.base_url)
        
        # Also check for additional result pages
        additional_urls = self._extract_additional_result_urls(html_content)
        
        for url in additional_urls:
            additional_content = await self.fetch_page(url)
            if additional_content:
                additional_pdfs = await self.extract_pdf_links(additional_content, url)
                pdf_results.extend(additional_pdfs)
                
        # Filter out already known PDFs
        new_pdfs = [pdf for pdf in pdf_results if not self._is_pdf_downloaded(pdf.url)]
        
        logger.info(f"Found {len(new_pdfs)} new PDFs out of {len(pdf_results)} total")
        return new_pdfs
        
    async def download_all_new_pdfs(self, limit: Optional[int] = None) -> Dict[str, int]:
        """Download all newly discovered PDFs"""
        stats = {"successful": 0, "failed": 0, "skipped": 0}
        
        new_pdfs = await self.scan_for_new_pdfs()
        
        if not new_pdfs:
            logger.info("No new PDFs found")
            return stats
        
        # Apply limit if specified
        if limit and limit > 0:
            logger.info(f"Limiting download to first {limit} PDFs")
            new_pdfs = new_pdfs[:limit]
            
        logger.info(f"Starting download of {len(new_pdfs)} PDFs...")
        
        # Download with limited concurrency
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent downloads
        
        async def download_with_semaphore(pdf_result):
            async with semaphore:
                success, skipped = await self.download_pdf(pdf_result)
                if skipped:
                    stats["skipped"] += 1
                elif success:
                    stats["successful"] += 1
                else:
                    stats["failed"] += 1
                
                # Small delay between downloads
                await asyncio.sleep(1)
                
        tasks = [download_with_semaphore(pdf) for pdf in new_pdfs]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"Download complete: {stats['successful']} successful, {stats['failed']} failed, {stats['skipped']} skipped")
        return stats
        
    async def cleanup_old_files(self, days_old: int = 30):
        """Clean up old downloaded files"""
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT download_path FROM pdf_results 
            WHERE date_found < ? AND downloaded = TRUE
        ''', (cutoff_date.isoformat(),))
        
        old_files = cursor.fetchall()
        
        for (file_path,) in old_files:
            if file_path:
                try:
                    Path(file_path).unlink(missing_ok=True)
                    logger.info(f"Cleaned up old file: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to cleanup {file_path}: {str(e)}")
                    
        conn.close()
        
    def get_download_stats(self) -> Dict:
        """Get download statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM pdf_results")
        total_pdfs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM pdf_results WHERE downloaded = TRUE")
        downloaded_pdfs = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(file_size) FROM pdf_results WHERE downloaded = TRUE")
        total_size = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_pdfs": total_pdfs,
            "downloaded_pdfs": downloaded_pdfs,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "success_rate": round((downloaded_pdfs / total_pdfs * 100) if total_pdfs > 0 else 0, 1)
        }

async def main():
    """Main execution function"""
    try:
        async with GGSIPUDownloader() as downloader:
            # Initial download of first 10 results
            logger.info("Starting initial download of first 10 results...")
            stats = await downloader.download_all_new_pdfs(limit=20 )
            
            download_stats = downloader.get_download_stats()
            
            print("\n" + "="*50)
            print("GGSIPU PDF Download Summary - Initial Download")
            print("="*50)
            print(f"Initial Downloads: {stats['successful']} successful, {stats['failed']} failed, {stats['skipped']} skipped")
            print(f"Total PDFs tracked: {download_stats['total_pdfs']}")
            print(f"Total downloaded: {download_stats['downloaded_pdfs']}")
            print(f"Total size: {download_stats['total_size_mb']} MB")
            print(f"Success rate: {download_stats['success_rate']}%")
            print("="*50)
            
            # Start continuous monitoring
            print("\nStarting continuous monitoring for new results...")
            logger.info("Starting continuous monitoring for new results...")
            
            try:
                while True:
                    await asyncio.sleep(3600)  # Check every hour
                    logger.info("Checking for new results...")
                    stats = await downloader.download_all_new_pdfs()
                    
                    if stats["successful"] > 0 or stats["failed"] > 0 or stats["skipped"] > 0:
                        download_stats = downloader.get_download_stats()
                        print("\n" + "-"*50)
                        print(f"New downloads: {stats['successful']} successful, {stats['failed']} failed, {stats['skipped']} skipped")
                        print(f"Total downloaded: {download_stats['downloaded_pdfs']}")
                        print("-"*50)
            except asyncio.CancelledError:
                logger.info("Monitoring stopped")
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
            
    except Exception as e:
        logger.error(f"Main execution error: {str(e)}")

if __name__ == "__main__":
    try:
        # Run the async main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript terminated by user")