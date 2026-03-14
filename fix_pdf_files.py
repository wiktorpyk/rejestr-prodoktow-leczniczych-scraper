#!/usr/bin/env python3
"""
PDF File Extraction and Repair Script

This script identifies and fixes PDF files that have extra metadata at the beginning
or are Microsoft Word documents incorrectly named as PDFs.

Usage: python fix_pdf_files.py [--dry-run] [--data-dir DIR]
"""

import os
import sys
import subprocess
import logging
import argparse
from pathlib import Path
from typing import List, Tuple, Dict

# Configuration
DATA_DIR = Path("data")
LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

class PDFRepairer:
    def __init__(self, data_dir: Path, dry_run: bool = False):
        self.data_dir = data_dir
        self.dry_run = dry_run
        self.stats = {
            'total_files': 0,
            'valid_pdfs': 0,
            'xmp_metadata_files': 0,
            'word_documents': 0,
            'processed_files': 0,
            'errors': 0
        }

    def get_file_type(self, file_path: Path) -> str:
        """Get file type using the 'file' command."""
        try:
            result = subprocess.run(
                ['file', str(file_path)],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            log.error(f"Error getting file type for {file_path}: {e}")
            return "unknown"

    def find_pdf_start(self, file_path: Path) -> int:
        """Find the start of PDF content in a file."""
        try:
            result = subprocess.run(
                ['grep', '-abo', '%PDF-', str(file_path)],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout:
                # Extract the byte offset from grep output (format: offset:pattern)
                offset = int(result.stdout.split(':')[0])
                return offset
        except subprocess.CalledProcessError:
            pass
        return -1

    def is_valid_pdf(self, file_path: Path) -> bool:
        """Check if file starts with PDF magic bytes."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(8)
                return header.startswith(b'%PDF-')
        except (IOError, OSError):
            return False

    def fix_xmp_metadata_file(self, file_path: Path, pdf_start: int) -> bool:
        """Extract PDF content from file with XMP metadata."""
        if self.dry_run:
            log.info(f"[DRY RUN] Would fix XMP metadata in: {file_path}")
            return True

        try:
            # Read from PDF start to end of file
            with open(file_path, 'rb') as infile:
                infile.seek(pdf_start)
                pdf_content = infile.read()

            # Write clean PDF back to file
            with open(file_path, 'wb') as outfile:
                outfile.write(pdf_content)

            log.info(f"Fixed XMP metadata in: {file_path}")
            return True
        except (IOError, OSError) as e:
            log.error(f"Error fixing XMP metadata in {file_path}: {e}")
            return False

    def convert_word_document(self, file_path: Path) -> bool:
        """Convert Word document to PDF."""
        if self.dry_run:
            log.info(f"[DRY RUN] Would convert Word document to PDF: {file_path}")
            return True

        # Determine the appropriate extension based on file type
        file_type = self.get_file_type(file_path)
        if 'Rich Text Format' in file_type:
            temp_ext = '.rtf'
        else:
            temp_ext = '.doc'
        
        # Create a temporary copy with appropriate extension
        temp_doc_path = file_path.with_suffix(temp_ext)
        original_path = file_path
        
        try:
            # Copy the file with appropriate extension for LibreOffice
            import shutil
            shutil.copy2(file_path, temp_doc_path)
            
            # Convert using LibreOffice
            conversion_command = [
                'libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', str(file_path.parent), str(temp_doc_path)
            ]

            print(f"Conversion command: {conversion_command}")
            
            result = subprocess.run(conversion_command, capture_output=False, text=True, check=True)
            
            # Check if the PDF was created
            expected_pdf = temp_doc_path.with_suffix('.pdf')
            if expected_pdf.exists():
                # Replace the original file with the converted PDF
                shutil.move(expected_pdf, original_path)
                log.info(f"Converted Word document to PDF: {file_path}")
                return True
            else:
                log.error(f"Conversion failed - PDF not created: {expected_pdf}")
                return False
                
        except (subprocess.CalledProcessError, FileNotFoundError, shutil.Error) as e:
            log.error(f"Error converting {file_path}: {e}")
            log.info("Install unoconv or libreoffice for Word to PDF conversion")
            return False
        finally:
            # Clean up temporary file
            if temp_doc_path.exists():
                try:
                    temp_doc_path.unlink()
                except OSError:
                    pass

    def process_file(self, file_path: Path) -> bool:
        """Process a single file based on its type."""
        file_type = self.get_file_type(file_path)
        self.stats['total_files'] += 1

        log.debug(f"Processing {file_path}: {file_type}")

        # Check if it's already a valid PDF
        if 'PDF document' in file_type and self.is_valid_pdf(file_path):
            self.stats['valid_pdfs'] += 1
            log.debug(f"Already valid PDF: {file_path}")
            return True

        # Handle XMP metadata files (identified as "data" but containing PDF)
        if file_type.endswith(': data'):
            pdf_start = self.find_pdf_start(file_path)
            if pdf_start >= 0:
                self.stats['xmp_metadata_files'] += 1
                success = self.fix_xmp_metadata_file(file_path, pdf_start)
                if success:
                    self.stats['processed_files'] += 1
                return success
            else:
                log.warning(f"File marked as 'data' but no PDF content found: {file_path}")

        # Handle Word documents
        if 'Composite Document File V2 Document' in file_type:
            self.stats['word_documents'] += 1
            success = self.convert_word_document(file_path)
            if success:
                self.stats['processed_files'] += 1
            return success

        # Handle RTF files
        if 'Rich Text Format' in file_type:
            self.stats['word_documents'] += 1
            success = self.convert_word_document(file_path)
            if success:
                self.stats['processed_files'] += 1
            return success

        log.warning(f"Unhandled file type: {file_path} -> {file_type}")
        return False

    def scan_and_process(self) -> Dict[str, int]:
        """Scan all files and process them."""
        if not self.data_dir.exists():
            log.error(f"Data directory does not exist: {self.data_dir}")
            return self.stats

        log.info(f"Scanning files in: {self.data_dir}")

        # Find all .pdf files
        pdf_files = list(self.data_dir.rglob("*.pdf"))
        log.info(f"Found {len(pdf_files)} PDF files to process")

        for file_path in pdf_files:
            try:
                self.process_file(file_path)
            except Exception as e:
                log.error(f"Error processing {file_path}: {e}")
                self.stats['errors'] += 1

        return self.stats

    def print_summary(self):
        """Print processing summary."""
        log.info("=" * 50)
        log.info("PROCESSING SUMMARY")
        log.info("=" * 50)
        log.info(f"Total files scanned: {self.stats['total_files']}")
        log.info(f"Valid PDFs (already correct): {self.stats['valid_pdfs']}")
        log.info(f"Files with XMP metadata: {self.stats['xmp_metadata_files']}")
        log.info(f"Word documents: {self.stats['word_documents']}")
        log.info(f"Successfully processed: {self.stats['processed_files']}")
        log.info(f"Errors: {self.stats['errors']}")
        log.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Fix PDF files with metadata issues")
    parser.add_argument(
        "--data-dir", type=str, default=str(DATA_DIR),
        help=f"Data directory to process (default: {DATA_DIR})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    data_dir = Path(args.data_dir)
    repairer = PDFRepairer(data_dir, args.dry_run)
    
    log.info(f"Starting PDF repair process (dry-run: {args.dry_run})")
    
    stats = repairer.scan_and_process()
    repairer.print_summary()
    
    if stats['errors'] > 0:
        log.warning(f"Completed with {stats['errors']} errors")
        sys.exit(1)
    else:
        log.info("Completed successfully")
        sys.exit(0)


if __name__ == "__main__":
    main()
