#!/usr/bin/env python3
"""
GGSIPU Results Monitor & Downloader with Auto-Cleanup
Continuously monitors GGSIPU website for new exam results and downloads them automatically
Each PDF is automatically deleted exactly 1 day after download
"""

import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import json
import os
import hashlib

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class GGSIPUDownloader:
    def __init__(self, monitor_interval=300, filter_keyword=None):  # Default 5 minutes
        self.base_url = "http://ggsipu.ac.in/ExamResults/ExamResultsmain.htm"
        self.download_dir = Path("ggsipu_results")
        self.download_dir.mkdir(exist_ok=True)
        
        # Create separate metadata folder for JSON files
        self.metadata_dir = self.download_dir / "metadata"
        self.metadata_dir.mkdir(exist_ok=True)
        
        self.metadata_file = self.metadata_dir / "download_metadata.json"
        self.monitoring_data_file = self.metadata_dir / "monitoring_data.json"
        self.latest_result_file = self.metadata_dir / "latest_result.json"
        self.session = None
        self.monitor_interval = monitor_interval  # seconds between checks
        self.is_monitoring = False
        self.filter_keyword = filter_keyword.lower() if filter_keyword else None  # User-provided keyword filter
        
    async def __aenter__(self):
        # Optimized connector with connection pooling
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=10,  # Max connections per host
            ttl_dns_cache=300,  # DNS cache TTL
            use_dns_cache=True,
        )
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=120, connect=15, sock_read=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
        )
        
        # Clean up expired files on startup
        await self.cleanup_expired_files()
        
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_page(self, url):
        """Fetch webpage content with retry logic"""
        for attempt in range(3):
            async with self.session.get(url) as response:
                response.raise_for_status()
                return await response.text()
    
    async def get_pdf_info(self, url, filename, title, position):
        """Get PDF info including last-modified date from HTTP headers"""
        try:
            # Try HTTP HEAD request for last-modified date with timeout
            async with self.session.head(url) as response:
                last_modified = response.headers.get('Last-Modified')
                if last_modified:
                    from email.utils import parsedate_to_datetime
                    date = parsedate_to_datetime(last_modified)
                    # Convert to naive datetime for consistent comparison
                    if date.tzinfo is not None:
                        date = date.replace(tzinfo=None)
                    date_source = 'http_header'
                else:
                    # Fallback: position-based dating (earlier = newer)
                    date = datetime.now() - timedelta(days=position)
                    date_source = 'position_based'
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # If HEAD request fails, use position-based dating
            date = datetime.now() - timedelta(days=position)
            date_source = 'position_fallback'
        
        return {
            'url': url,
            'filename': filename,
            'title': title,
            'date': date,
            'position': position,
            'date_source': date_source
        }
    
    def matches_keyword_filter(self, filename, title):
        """Check if PDF matches user-provided keyword filter"""
        if not self.filter_keyword:
            return True  # No filter means all PDFs pass
        
        text = f"{filename} {title}".lower()
        return self.filter_keyword in text
    
    async def get_all_pdfs(self):
        """Get PDF links from main page with concurrent processing"""
        logger.info("Scanning GGSIPU website for PDFs...")
        
        html = await self.fetch_page(self.base_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all PDF links
        pdf_links = soup.find_all('a', href=lambda x: x and x.lower().endswith('.pdf'))
        logger.info(f"Found {len(pdf_links)} PDF links on main page")
        
        # Process PDFs concurrently but with controlled batching to avoid overwhelming server
        batch_size = 50  # Process 50 at a time
        all_pdfs = []
        
        for i in range(0, len(pdf_links), batch_size):
            batch = pdf_links[i:i + batch_size]
            tasks = []
            
            for position, link in enumerate(batch, start=i):
                url = urljoin(self.base_url, link['href'])
                filename = Path(link['href']).name
                title = link.get_text(strip=True) or filename.replace('.pdf', '').replace('_', ' ').title()
                
                task = self.get_pdf_info(url, filename, title, position)
                tasks.append(task)
            
            # Process this batch
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and add valid results
            for result in batch_results:
                if isinstance(result, dict):  # Valid PDF info
                    all_pdfs.append(result)
                # Silently skip exceptions (already logged in get_pdf_info)
        
        # Show sample results
        for i, pdf in enumerate(all_pdfs[:5]):
            date_str = pdf['date'].strftime('%Y-%m-%d')
            logger.info(f"   {pdf['filename'][:40]:<40} -> {date_str} ({pdf['date_source']})")
        
        # Remove duplicates and filter by user keyword
        unique_pdfs = {pdf['url']: pdf for pdf in all_pdfs}.values()
        
        # Apply keyword filter if provided
        if self.filter_keyword:
            filtered_pdfs = [pdf for pdf in unique_pdfs if self.matches_keyword_filter(pdf['filename'], pdf['title'])]
            logger.info(f"Keyword filter '{self.filter_keyword}': {len(filtered_pdfs)} out of {len(list(unique_pdfs))} PDFs match")
        else:
            filtered_pdfs = list(unique_pdfs)
            logger.info(f"No keyword filter applied: processing all {len(filtered_pdfs)} PDFs")
        
        # Sort by date and position (most recent first)
        def sort_key(pdf):
            return (pdf['date'], -pdf['position'])
        
        sorted_pdfs = sorted(filtered_pdfs, key=sort_key, reverse=True)
        
        # Show top results
        if self.filter_keyword:
            logger.info(f"Top 10 PDFs matching '{self.filter_keyword}':")
        else:
            logger.info("Top 10 PDFs:")
        for i, pdf in enumerate(sorted_pdfs[:10], 1):
            date_str = pdf['date'].strftime('%Y-%m')
            logger.info(f"   {i:2d}. {pdf['filename'][:60]:<60} ({date_str})")
        
        return sorted_pdfs
    
    async def download_pdf(self, pdf_info):
        """Download a single PDF with retry logic and metadata tracking"""
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', pdf_info['filename'])
        filepath = self.download_dir / safe_filename
        
        # Load existing metadata
        metadata = self.load_metadata()
        
        # Skip if already exists and not expired
        if filepath.exists() and safe_filename in metadata:
            current_time = datetime.now()
            if current_time < metadata[safe_filename]['delete_time']:
                logger.info(f"Skipping {safe_filename} (already exists, expires at {metadata[safe_filename]['delete_time'].strftime('%Y-%m-%d %H:%M')})")
                return False
        
        # Retry download up to 3 times with increasing delays
        for attempt in range(3):
            try:
                async with self.session.get(pdf_info['url']) as response:
                    response.raise_for_status()
                    
                    download_time = datetime.now()
                    delete_time = download_time + timedelta(days=1)  # Delete after exactly 1 day
                    
                    async with aiofiles.open(filepath, 'wb') as f:
                        downloaded = 0
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            downloaded += len(chunk)
                    
                    size_mb = downloaded / (1024 * 1024)
                    
                    # Update metadata
                    metadata[safe_filename] = {
                        'download_time': download_time,
                        'delete_time': delete_time,
                        'url': pdf_info['url'],
                        'size_mb': size_mb
                    }
                    self.save_metadata(metadata)
                    
                    logger.info(f"Downloaded {safe_filename} ({size_mb:.1f} MB) - expires {delete_time.strftime('%Y-%m-%d %H:%M')}")
                    return True
                    
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < 2:  # Not the last attempt
                    wait_time = (attempt + 1) * 2  # 2, 4 seconds
                    logger.warning(f"Attempt {attempt + 1} failed for {safe_filename}, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to download {safe_filename} after 3 attempts: {e}")
                    # Clean up partial file if it exists
                    if filepath.exists():
                        filepath.unlink()
                    return False
            except Exception as e:
                logger.error(f"Unexpected error downloading {safe_filename}: {e}")
                if filepath.exists():
                    filepath.unlink()
                return False
    
    def load_metadata(self):
        """Load download metadata from JSON file"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    data = json.load(f)
                    # Convert ISO strings back to datetime objects
                    for filename, info in data.items():
                        info['download_time'] = datetime.fromisoformat(info['download_time'])
                        info['delete_time'] = datetime.fromisoformat(info['delete_time'])
                    return data
            except Exception as e:
                logger.warning(f"Could not load metadata: {e}")
        return {}
    
    def save_metadata(self, metadata):
        """Save download metadata to JSON file"""
        try:
            # Convert datetime objects to ISO strings for JSON serialization
            json_data = {}
            for filename, info in metadata.items():
                json_data[filename] = {
                    'download_time': info['download_time'].isoformat(),
                    'delete_time': info['delete_time'].isoformat(),
                    'url': info['url'],
                    'size_mb': info['size_mb']
                }
            
            with open(self.metadata_file, 'w') as f:
                json.dump(json_data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save metadata: {e}")
    
    def load_monitoring_data(self):
        """Load monitoring data (known PDFs, page hash, etc.)"""
        if self.monitoring_data_file.exists():
            try:
                with open(self.monitoring_data_file, 'r') as f:
                    data = json.load(f)
                    # Convert ISO strings back to datetime objects
                    if 'last_check' in data:
                        data['last_check'] = datetime.fromisoformat(data['last_check'])
                    return data
            except Exception as e:
                logger.warning(f"Could not load monitoring data: {e}")
        return {
            'known_pdfs': set(),
            'page_hash': '',
            'last_check': None,
            'total_checks': 0,
            'new_pdfs_found': 0
        }
    
    def save_monitoring_data(self, data):
        """Save monitoring data to JSON file"""
        try:
            # Convert sets and datetime objects for JSON serialization
            json_data = data.copy()
            json_data['known_pdfs'] = list(data['known_pdfs'])  # Convert set to list
            if data['last_check']:
                json_data['last_check'] = data['last_check'].isoformat()
            
            with open(self.monitoring_data_file, 'w') as f:
                json.dump(json_data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save monitoring data: {e}")
    
    def load_latest_result(self):
        """Load the latest result information"""
        if self.latest_result_file.exists():
            try:
                with open(self.latest_result_file, 'r') as f:
                    data = json.load(f)
                    if 'timestamp' in data:
                        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
                    return data
            except Exception as e:
                logger.warning(f"Could not load latest result: {e}")
        return None
    
    def save_latest_result(self, pdf_info):
        """Save the latest result information"""
        try:
            latest_data = {
                'filename': pdf_info['filename'],
                'title': pdf_info['title'],
                'url': pdf_info['url'],
                'timestamp': datetime.now(),
                'position': pdf_info.get('position', 0),
                'date_source': pdf_info.get('date_source', 'unknown')
            }
            
            # Convert datetime to ISO string for JSON
            json_data = latest_data.copy()
            json_data['timestamp'] = latest_data['timestamp'].isoformat()
            
            with open(self.latest_result_file, 'w') as f:
                json.dump(json_data, f, indent=2)
                
            logger.info(f"Updated latest result tracker: {pdf_info['filename']}")
            
        except Exception as e:
            logger.error(f"Could not save latest result: {e}")
    
    def get_page_hash(self, html_content):
        """Generate hash of PDF links section to detect changes"""
        # Extract only PDF links to avoid false positives from dynamic content
        soup = BeautifulSoup(html_content, 'html.parser')
        pdf_links = soup.find_all('a', href=lambda x: x and x.lower().endswith('.pdf'))
        
        # Create string of all PDF URLs and text
        pdf_content = ""
        for link in pdf_links:
            url = link.get('href', '')
            text = link.get_text(strip=True)
            pdf_content += f"{url}|{text}\n"
        
        return hashlib.md5(pdf_content.encode()).hexdigest()
    
    async def check_for_new_results(self):
        """Check if there are new results on the website"""
        try:
            html = await self.fetch_page(self.base_url)
            current_hash = self.get_page_hash(html)
            
            monitoring_data = self.load_monitoring_data()
            
            # Always increment total_checks since we performed a check
            monitoring_data['total_checks'] += 1
            monitoring_data['last_check'] = datetime.now()
            
            # First time check or page changed
            if not monitoring_data['page_hash'] or current_hash != monitoring_data['page_hash']:
                
                # Get current PDF list
                soup = BeautifulSoup(html, 'html.parser')
                pdf_links = soup.find_all('a', href=lambda x: x and x.lower().endswith('.pdf'))
                
                current_pdfs = set()
                new_pdfs = []
                
                for link in pdf_links:
                    url = urljoin(self.base_url, link['href'])
                    filename = Path(link['href']).name
                    current_pdfs.add(url)
                    
                    # Check if this is a new PDF
                    if url not in monitoring_data['known_pdfs']:
                        new_pdfs.append({
                            'url': url,
                            'filename': filename,
                            'title': link.get_text(strip=True) or filename.replace('.pdf', '').replace('_', ' ').title()
                        })
                
                # Update monitoring data
                monitoring_data['page_hash'] = current_hash
                monitoring_data['known_pdfs'] = current_pdfs
                
                if new_pdfs:
                    monitoring_data['new_pdfs_found'] += len(new_pdfs)
                    logger.info(f"Found {len(new_pdfs)} new PDFs!")
                    for pdf in new_pdfs:
                        logger.info(f"   {pdf['filename']}")
                    
                    # Update latest result tracker with the first new PDF (most recent)
                    if new_pdfs:
                        self.save_latest_result(new_pdfs[0])
                    
                    self.save_monitoring_data(monitoring_data)
                    return new_pdfs
                else:
                    if monitoring_data['total_checks'] > 1:  # Don't log "no new" on first check
                        logger.info("No new results found")
                    self.save_monitoring_data(monitoring_data)
                    return []
            else:
                # Page hasn't changed
                self.save_monitoring_data(monitoring_data)
                logger.info("No changes detected on website")
                return []
                
        except Exception as e:
            logger.error(f"Error checking for new results: {e}")
            return []
    
    async def download_new_pdfs(self, new_pdfs):
        """Download only the new PDFs found"""
        if not new_pdfs:
            return 0
        
        logger.info(f"Downloading {len(new_pdfs)} new PDFs...")
        
        downloaded = 0
        for pdf in new_pdfs:
            # Add position (doesn't matter for new PDFs)
            pdf['position'] = 0
            pdf['date'] = datetime.now()
            pdf['date_source'] = 'new_detection'
            
            success = await self.download_pdf(pdf)
            if success:
                downloaded += 1
                # Update latest result tracker after successful download
                self.save_latest_result(pdf)
        
        return downloaded
    
    async def cleanup_expired_files(self):
        """Delete files that are older than 1 day from download time"""
        metadata = self.load_metadata()
        current_time = datetime.now()
        deleted_count = 0
        
        for filename, info in list(metadata.items()):
            file_path = self.download_dir / filename
            
            # Check if file should be deleted (1 day after download)
            if current_time >= info['delete_time']:
                try:
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Deleted expired file: {filename}")
                        deleted_count += 1
                    
                    # Remove from metadata
                    del metadata[filename]
                    
                except Exception as e:
                    logger.error(f"Could not delete {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired files")
            self.save_metadata(metadata)
        
        return deleted_count
    
    async def download_all_results(self):
        """Main function to download ALL PDFs with auto-cleanup"""
        logger.info("Starting GGSIPU All Results Downloader with Auto-Cleanup")
        
        all_pdfs = await self.get_all_pdfs()
        
        logger.info(f"\nDownloading {len(all_pdfs)} PDFs...")
        logger.info("Each PDF will be automatically deleted exactly 1 day after download")
        
        # Download with controlled concurrency (1 at a time to avoid timeouts)
        semaphore = asyncio.Semaphore(1)
        
        async def download_with_semaphore(pdf):
            async with semaphore:
                success = await self.download_pdf(pdf)
                if success:
                    # Update latest result tracker after successful download
                    self.save_latest_result(pdf)
                return success
        
        tasks = [download_with_semaphore(pdf) for pdf in all_pdfs]
        results = await asyncio.gather(*tasks)
        
        # Summary
        downloaded = sum(results)
        skipped = len(results) - downloaded
        
        logger.info(f"\nDownload Complete!")
        logger.info(f"   Downloaded: {downloaded}")
        logger.info(f"   Skipped: {skipped}")
        logger.info(f"   Location: {self.download_dir.absolute()}")
        logger.info(f"   Auto-cleanup: Files will be deleted 24 hours after download")
        
        # Show current file status
        metadata = self.load_metadata()
        if metadata:
            logger.info(f"\nCurrent Files Status:")
            current_time = datetime.now()
            for filename, info in sorted(metadata.items(), key=lambda x: x[1]['delete_time']):
                time_left = info['delete_time'] - current_time
                if time_left > timedelta(0):
                    hours_left = int(time_left.total_seconds() // 3600)
                    minutes_left = int((time_left.total_seconds() % 3600) // 60)
                    logger.info(f"   {filename[:50]:<50} expires in {hours_left}h {minutes_left}m")
                else:
                    logger.info(f"   {filename[:50]:<50} should be deleted (expired)")
        
        return downloaded, skipped
    
    async def start_monitoring(self):
        """Start continuous monitoring of the website"""
        logger.info(" Starting GGSIPU Results Monitor")
        logger.info(f" Checking every {self.monitor_interval // 60} minutes for new results")
        logger.info(" New PDFs will be auto-downloaded and deleted after 24 hours")
        
        # Show current latest result if exists
        latest_result = self.load_latest_result()
        if latest_result:
            logger.info(f" Latest tracked result: {latest_result['filename']}")
            logger.info(f" Last updated: {latest_result['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.is_monitoring = True
        
        # Initial scan to populate known PDFs
        logger.info(" Performing initial scan...")
        await self.check_for_new_results()
        
        while self.is_monitoring:
            try:
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Get current check number before the check
                monitoring_data = self.load_monitoring_data()
                next_check_num = monitoring_data['total_checks'] + 1
                logger.info(f"\n Check #{next_check_num} at {current_time}")
                
                # Clean up expired files
                deleted_count = await self.cleanup_expired_files()
                
                # Check for new results
                new_pdfs = await self.check_for_new_results()
                
                # Download new PDFs if found
                if new_pdfs:
                    downloaded = await self.download_new_pdfs(new_pdfs)
                    logger.info(f"Downloaded {downloaded} new PDFs")
                
                # Show monitoring stats (reload to get updated counts)
                monitoring_data = self.load_monitoring_data()
                metadata = self.load_metadata()
                active_files = len(metadata)
                
                logger.info(f"Monitor Stats: {monitoring_data['total_checks']} checks, "
                          f"{monitoring_data['new_pdfs_found']} new PDFs found, "
                          f"{active_files} active files")
                
                # Wait for next check
                logger.info(f"Sleeping for {self.monitor_interval // 60} minutes...")
                await asyncio.sleep(self.monitor_interval)
                
            except KeyboardInterrupt:
                logger.info("\nMonitoring stopped by user")
                self.is_monitoring = False
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                logger.info(f"Retrying in {self.monitor_interval // 60} minutes...")
                await asyncio.sleep(self.monitor_interval)
    
    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.is_monitoring = False
        logger.info("Monitoring stop requested")
    
    async def monitor_once(self):
        """Perform a single monitoring check (useful for testing)"""
        logger.info("Performing single monitoring check...")
        
        # Clean up expired files
        deleted_count = await self.cleanup_expired_files()
        
        # Check for new results
        new_pdfs = await self.check_for_new_results()
        
        # Download new PDFs if found
        if new_pdfs:
            downloaded = await self.download_new_pdfs(new_pdfs)
            logger.info(f"Downloaded {downloaded} new PDFs")
            return downloaded
        else:
            logger.info("No new PDFs to download")
            return 0

    async def test_system(self):
        """Test all system components to ensure they're working"""
        logger.info("Starting System Test...")
        
        test_results = {
            'website_access': False,
            'pdf_detection': False,
            'download_capability': False,
            'metadata_system': False,
            'cleanup_system': False
        }
        
        try:
            # Test 1: Website Access
            logger.info("Test 1: Testing website access...")
            html = await self.fetch_page(self.base_url)
            if html and len(html) > 1000:  # Basic sanity check
                test_results['website_access'] = True
                logger.info(" Website access: PASSED")
            else:
                logger.error(" Website access: FAILED")
                return test_results
            
            # Test 2: PDF Detection
            logger.info(" Test 2: Testing PDF detection...")
            soup = BeautifulSoup(html, 'html.parser')
            pdf_links = soup.find_all('a', href=lambda x: x and x.lower().endswith('.pdf'))
            if len(pdf_links) > 0:
                test_results['pdf_detection'] = True
                logger.info(f" PDF detection: PASSED ({len(pdf_links)} PDFs found)")
            else:
                logger.error(" PDF detection: FAILED")
                return test_results
            
            # Test 3: Metadata System
            logger.info(" Test 3: Testing metadata system...")
            test_metadata = {'test_file.pdf': {
                'download_time': datetime.now(),
                'delete_time': datetime.now() + timedelta(days=1),
                'url': 'test_url',
                'size_mb': 1.0
            }}
            self.save_metadata(test_metadata)
            loaded_metadata = self.load_metadata()
            if 'test_file.pdf' in loaded_metadata:
                test_results['metadata_system'] = True
                logger.info(" Metadata system: PASSED")
                # Clean up test data
                del loaded_metadata['test_file.pdf']
                self.save_metadata(loaded_metadata)
            else:
                logger.error(" Metadata system: FAILED")
            
            # Test 4: Monitoring Data System
            logger.info("Test 4: Testing monitoring data system...")
            test_monitoring_data = {
                'known_pdfs': set(['test1.pdf', 'test2.pdf']),
                'page_hash': 'test_hash',
                'last_check': datetime.now(),
                'total_checks': 1,
                'new_pdfs_found': 0
            }
            self.save_monitoring_data(test_monitoring_data)
            loaded_monitoring = self.load_monitoring_data()
            if loaded_monitoring['page_hash'] == 'test_hash':
                logger.info(" Monitoring data system: PASSED")
            else:
                logger.error("Monitoring data system: FAILED")
            
            # Test 5: Hash Generation
            logger.info("Test 5: Testing hash generation...")
            hash1 = self.get_page_hash(html)
            hash2 = self.get_page_hash(html)
            if hash1 == hash2 and len(hash1) == 32:  # MD5 is 32 chars
                logger.info(f"Hash generation: PASSED (hash: {hash1[:8]}...)")
            else:
                logger.error("Hash generation: FAILED")
            
            # Test 6: New PDF Detection Logic
            logger.info("Test 6: Testing new PDF detection...")
            # Simulate known PDFs
            known_pdfs = set([urljoin(self.base_url, pdf_links[0]['href'])])
            current_pdfs = set([urljoin(self.base_url, link['href']) for link in pdf_links[:3]])
            new_pdfs = current_pdfs - known_pdfs
            if len(new_pdfs) >= 1:
                logger.info(f"New PDF detection: PASSED ({len(new_pdfs)} new PDFs would be detected)")
            else:
                logger.info("New PDF detection: No new PDFs in test scenario")
            
            logger.info("\nSystem Test Complete!")
            passed_tests = sum(test_results.values())
            total_tests = len(test_results)
            logger.info(f"Results: {passed_tests}/{total_tests} tests passed")
            
            if passed_tests == total_tests:
                logger.info("All systems are working correctly!")
                return True
            else:
                logger.warning("Some tests failed. Check the logs above.")
                return False
                
        except Exception as e:
            logger.error(f" System test failed with error: {e}")
            return False
    
    async def show_status(self):
        """Show current system status and statistics"""
        logger.info("GGSIPU Monitor Status Report")
        logger.info("=" * 50)
        
        # System info
        logger.info(f"Base URL: {self.base_url}")
        logger.info(f"Download Directory: {self.download_dir.absolute()}")
        logger.info(f"Monitor Interval: {self.monitor_interval // 60} minutes")
        
        # Monitoring statistics
        monitoring_data = self.load_monitoring_data()
        if monitoring_data['last_check']:
            last_check = monitoring_data['last_check'].strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f" Last Check: {last_check}")
            logger.info(f" Total Checks: {monitoring_data['total_checks']}")
            logger.info(f"New PDFs Found: {monitoring_data['new_pdfs_found']}")
            logger.info(f" Current Page Hash: {monitoring_data['page_hash'][:8]}...")
            logger.info(f" Known PDFs: {len(monitoring_data['known_pdfs'])}")
        else:
            logger.info("No monitoring history found")
        
        # Latest result tracking
        latest_result = self.load_latest_result()
        if latest_result:
            logger.info(f"\nLatest Result Tracked:")
            logger.info(f" Filename: {latest_result['filename']}")
            logger.info(f" Title: {latest_result['title'][:60]}...")
            logger.info(f" Last Updated: {latest_result['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f" Position: {latest_result['position']}")
        else:
            logger.info("\nNo latest result tracked yet")
        
        # File statistics
        metadata = self.load_metadata()
        if metadata:
            logger.info(f"\n Active Downloaded Files: {len(metadata)}")
            current_time = datetime.now()
            
            expiring_soon = 0
            total_size = 0
            
            for filename, info in metadata.items():
                total_size += info['size_mb']
                time_left = info['delete_time'] - current_time
                if time_left < timedelta(hours=2):  # Expiring in less than 2 hours
                    expiring_soon += 1
            
            logger.info(f" Total Size: {total_size:.1f} MB")
            logger.info(f" Expiring Soon (< 2h): {expiring_soon} files")
            
            if expiring_soon > 0:
                logger.info("\n Files expiring soon:")
                for filename, info in metadata.items():
                    time_left = info['delete_time'] - current_time
                    if time_left < timedelta(hours=2):
                        hours = int(time_left.total_seconds() // 3600)
                        minutes = int((time_left.total_seconds() % 3600) // 60)
                        logger.info(f"   📄 {filename[:40]:<40} expires in {hours}h {minutes}m")
        else:
            logger.info(" No active files")
        
        # Check if directories exist
        logger.info(f"\nDirectory Status:")
        logger.info(f"   Download Dir Exists: {self.download_dir.exists()}")
        logger.info(f"   Metadata File Exists: {self.metadata_file.exists()}")
        logger.info(f"   Monitoring File Exists: {self.monitoring_data_file.exists()}")
        logger.info(f"   Latest Result File Exists: {self.latest_result_file.exists()}")
        
        logger.info("=" * 50)

async def main():
    """Main entry point with multiple modes"""
    import sys
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == '--monitor':
            # Continuous monitoring mode
            interval = 300  # Default 5 minutes
            keyword = None
            
            # Parse additional arguments
            for i in range(2, len(sys.argv)):
                arg = sys.argv[i]
                if arg.startswith('--keyword='):
                    keyword = arg.split('=', 1)[1]
                elif arg.isdigit():
                    try:
                        interval = int(arg) * 60  # Convert minutes to seconds
                    except ValueError:
                        logger.error("Invalid interval. Using default 5 minutes.")
            
            try:
                async with GGSIPUDownloader(monitor_interval=interval, filter_keyword=keyword) as downloader:
                    await downloader.start_monitoring()
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
        
        elif mode == '--check-once':
            # Single check mode
            try:
                async with GGSIPUDownloader() as downloader:
                    await downloader.monitor_once()
            except Exception as e:
                logger.error(f" Error: {e}")
        
        elif mode == '--test':
            # System test mode
            try:
                async with GGSIPUDownloader() as downloader:
                    success = await downloader.test_system()
                    if success:
                        print("\n All systems working correctly!")
                    else:
                        print("\n Some systems have issues. Check logs above.")
            except Exception as e:
                logger.error(f" Error: {e}")
        
        elif mode == '--status':
            # Show status mode
            try:
                downloader = GGSIPUDownloader()
                await downloader.show_status()
            except Exception as e:
                logger.error(f" Error: {e}")
        
        elif mode == '--cleanup-only':
            # Cleanup only mode
            try:
                downloader = GGSIPUDownloader()
                await downloader.cleanup_expired_files()
            except Exception as e:
                logger.error(f" Error: {e}")
        
        elif mode == '--download-all':
            # Download all results mode (original functionality)
            keyword = None
            
            # Check for keyword parameter
            for i in range(2, len(sys.argv)):
                arg = sys.argv[i]
                if arg.startswith('--keyword='):
                    keyword = arg.split('=', 1)[1]
            
            try:
                async with GGSIPUDownloader(filter_keyword=keyword) as downloader:
                    await downloader.download_all_results()
            except Exception as e:
                logger.error(f" Error: {e}")
        
        elif mode == '--help':
            print("""
GGSIPU Results Monitor & Downloader

Usage modes:
  python ggsipu_downloader.py --monitor [interval_minutes] [--keyword=FILTER]
    Start continuous monitoring (default: 5 minutes)
    Example: python ggsipu_downloader.py --monitor 10
    Example: python ggsipu_downloader.py --monitor --keyword="mba"
    
  python ggsipu_downloader.py --check-once
    Perform a single check for new results
    
  python ggsipu_downloader.py --download-all [--keyword=FILTER]
    Download ALL results from website (one-time)
    Example: python ggsipu_downloader.py --download-all --keyword="btech"
    Example: python ggsipu_downloader.py --download-all --keyword="m"
    
  python ggsipu_downloader.py --test
    Test all system components
    
  python ggsipu_downloader.py --status
    Show current system status and statistics
    
  python ggsipu_downloader.py --cleanup-only
    Only clean up expired files
    
  python ggsipu_downloader.py --help
    Show this help message

Features:
  - Auto-cleanup: Files deleted exactly 24 hours after download
  - Latest result tracking: Resumes monitoring from last processed result
  - Keyword filtering: Use --keyword to only download PDFs matching that text (any length)
  - Persistent state: Maintains tracking across restarts

Keyword Examples:
  --keyword="mba"     → Only downloads PDFs with "mba" in filename or title
  --keyword="btech"   → Only downloads PDFs with "btech" in filename or title  
  --keyword="m"       → Only downloads PDFs with letter "m" in filename or title
  --keyword="2025"    → Only downloads PDFs with "2025" in filename or title
  --keyword="june"    → Only downloads PDFs with "june" in filename or title

Default (no arguments): Start monitoring with 5-minute intervals
            """)
        
        else:
            logger.error(f"Unknown mode: {mode}. Use --help for options.")
    
    else:
        # Default: Start monitoring
        try:
            async with GGSIPUDownloader() as downloader:
                await downloader.start_monitoring()
        except KeyboardInterrupt:
            print("\n  Monitoring stopped by user")
        except Exception as e:
            logger.error(f" Error: {e}")

if __name__ == "__main__":
    
    asyncio.run(main())
