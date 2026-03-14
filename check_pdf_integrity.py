#!/usr/bin/env python3
"""
PDF Integrity Checker Script

This script checks the integrity of PDF files in the data directory and reports
various issues including corruption, format problems, and structural issues.

Usage: python check_pdf_integrity.py [--data-dir DIR] [--report-file FILE] [--verbose]
"""

import os
import sys
import subprocess
import logging
import argparse
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

# Configuration
DATA_DIR = Path("data")
LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

class PDFIntegrityChecker:
    def __init__(self, data_dir: Path, report_file: Optional[Path] = None):
        self.data_dir = data_dir
        self.report_file = report_file
        self.stats = {
            'total_files': 0,
            'valid_pdfs': 0,
            'corrupted_pdfs': 0,
            'non_pdf_files': 0,
            'missing_files': 0,
            'empty_files': 0,
            'xmp_metadata_files': 0,
            'word_documents': 0,
            'encrypted_pdfs': 0,
            'size_errors': 0
        }
        self.issues = []

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

    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes."""
        try:
            return file_path.stat().st_size
        except OSError:
            return 0

    def is_valid_pdf_header(self, file_path: Path) -> bool:
        """Check if file starts with PDF magic bytes."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(8)
                return header.startswith(b'%PDF-')
        except (IOError, OSError):
            return False

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
                offset = int(result.stdout.split(':')[0])
                return offset
        except subprocess.CalledProcessError:
            pass
        return -1

    def check_pdf_structure(self, file_path: Path) -> Dict[str, any]:
        """Check PDF structure using pdfinfo or similar tools."""
        issues = []
        
        try:
            # Try to use pdfinfo if available
            result = subprocess.run(
                ['pdfinfo', str(file_path)],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse pdfinfo output for potential issues
            for line in result.stdout.split('\n'):
                if 'Encrypted:' in line and 'yes' in line.lower():
                    issues.append("PDF is encrypted")
                    self.stats['encrypted_pdfs'] += 1
                    
        except (subprocess.CalledProcessError, FileNotFoundError):
            # pdfinfo not available or failed, try basic checks
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    
                # Check for PDF end marker
                if not content.endswith(b'%%EOF'):
                    issues.append("Missing or invalid EOF marker")
                    
                # Check for basic PDF structure
                if b'obj' not in content and b'endobj' not in content:
                    issues.append("Missing PDF object structure")
                    
            except (IOError, OSError):
                issues.append("Cannot read file content")
        
        return issues

    def check_file_integrity(self, file_path: Path) -> Dict[str, any]:
        """Perform comprehensive integrity check on a single file."""
        result = {
            'file_path': str(file_path),
            'status': 'valid',
            'issues': [],
            'file_type': '',
            'size_bytes': 0,
            'pdf_start_offset': -1
        }
        
        # Check if file exists
        if not file_path.exists():
            result['status'] = 'missing'
            result['issues'].append("File does not exist")
            self.stats['missing_files'] += 1
            return result
        
        # Get file size
        result['size_bytes'] = self.get_file_size(file_path)
        
        # Check if file is empty
        if result['size_bytes'] == 0:
            result['status'] = 'corrupted'
            result['issues'].append("File is empty")
            self.stats['empty_files'] += 1
            return result
        
        # Get file type
        result['file_type'] = self.get_file_type(file_path)
        
        # Check if it's a PDF file
        if not file_path.suffix.lower() == '.pdf':
            result['status'] = 'invalid_format'
            result['issues'].append(f"File has .pdf extension but is: {result['file_type']}")
            self.stats['non_pdf_files'] += 1
            return result
        
        # Check PDF header
        if not self.is_valid_pdf_header(file_path):
            # Check if it's a file with XMP metadata
            pdf_start = self.find_pdf_start(file_path)
            result['pdf_start_offset'] = pdf_start
            
            if pdf_start >= 0:
                result['status'] = 'xmp_metadata'
                result['issues'].append(f"File has XMP metadata - PDF starts at offset {pdf_start}")
                self.stats['xmp_metadata_files'] += 1
            else:
                # Check if it's a Word document
                file_type = result['file_type']
                if 'Composite Document File V2 Document' in file_type:
                    result['status'] = 'word_document'
                    result['issues'].append("File is a Word document, not a PDF")
                    self.stats['word_documents'] += 1
                elif 'Rich Text Format' in file_type:
                    result['status'] = 'word_document'
                    result['issues'].append("File is an RTF document, not a PDF")
                    self.stats['word_documents'] += 1
                else:
                    result['status'] = 'corrupted'
                    result['issues'].append("File does not have valid PDF header")
                    self.stats['corrupted_pdfs'] += 1
        else:
            # File has valid PDF header, check structure
            structure_issues = self.check_pdf_structure(file_path)
            if structure_issues:
                result['issues'].extend(structure_issues)
                if result['status'] == 'valid':
                    result['status'] = 'structure_issues'
            
            # Check for reasonable file size
            if result['size_bytes'] < 100:  # Very small PDFs are likely corrupted
                result['status'] = 'corrupted'
                result['issues'].append("File size too small for a valid PDF")
                self.stats['size_errors'] += 1
        
        # Update valid PDF count
        if result['status'] == 'valid':
            self.stats['valid_pdfs'] += 1
        
        return result

    def scan_all_files(self) -> List[Dict[str, any]]:
        """Scan all PDF files and check their integrity."""
        if not self.data_dir.exists():
            log.error(f"Data directory does not exist: {self.data_dir}")
            return []
        
        log.info(f"Scanning files in: {self.data_dir}")
        
        # Find all .pdf files
        pdf_files = list(self.data_dir.rglob("*.pdf"))
        log.info(f"Found {len(pdf_files)} PDF files to check")
        
        results = []
        
        for file_path in pdf_files:
            try:
                result = self.check_file_integrity(file_path)
                results.append(result)
                self.stats['total_files'] += 1
                
                # Log issues found
                if result['status'] != 'valid':
                    log.warning(f"Issue found in {file_path}: {result['issues']}")
                    self.issues.append(result)
                
            except Exception as e:
                log.error(f"Error checking {file_path}: {e}")
                self.stats['total_files'] += 1
                self.stats['corrupted_pdfs'] += 1
                results.append({
                    'file_path': str(file_path),
                    'status': 'error',
                    'issues': [f"Error during check: {e}"],
                    'file_type': 'unknown',
                    'size_bytes': 0,
                    'pdf_start_offset': -1
                })
        
        return results

    def generate_report(self, results: List[Dict[str, any]]) -> Dict[str, any]:
        """Generate a comprehensive integrity report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'data_directory': str(self.data_dir),
            'summary': self.stats,
            'issues_found': len(self.issues),
            'problematic_files': results if self.issues else [],
            'categories': {
                'missing_files': [r for r in results if r['status'] == 'missing'],
                'corrupted_files': [r for r in results if r['status'] == 'corrupted'],
                'xmp_metadata_files': [r for r in results if r['status'] == 'xmp_metadata'],
                'word_documents': [r for r in results if r['status'] == 'word_document'],
                'non_pdf_files': [r for r in results if r['status'] == 'invalid_format'],
                'structure_issues': [r for r in results if r['status'] == 'structure_issues'],
                'encrypted_files': [r for r in results if 'encrypted' in ' '.join(r['issues']).lower()],
                'size_errors': [r for r in results if r['status'] == 'corrupted' and 'size' in ' '.join(r['issues']).lower()]
            }
        }
        
        return report

    def print_summary(self):
        """Print integrity check summary."""
        log.info("=" * 60)
        log.info("PDF INTEGRITY CHECK SUMMARY")
        log.info("=" * 60)
        log.info(f"Total files scanned: {self.stats['total_files']}")
        log.info(f"Valid PDFs: {self.stats['valid_pdfs']}")
        log.info(f"Corrupted PDFs: {self.stats['corrupted_pdfs']}")
        log.info(f"Files with XMP metadata: {self.stats['xmp_metadata_files']}")
        log.info(f"Word documents: {self.stats['word_documents']}")
        log.info(f"Non-PDF files: {self.stats['non_pdf_files']}")
        log.info(f"Empty files: {self.stats['empty_files']}")
        log.info(f"Missing files: {self.stats['missing_files']}")
        log.info(f"Encrypted PDFs: {self.stats['encrypted_pdfs']}")
        log.info(f"Size errors: {self.stats['size_errors']}")
        log.info(f"Total issues found: {len(self.issues)}")
        
        if self.issues:
            log.info("=" * 60)
            log.info("ISSUES SUMMARY BY CATEGORY:")
            log.info("=" * 60)
            
            categories = {
                'Corrupted': self.stats['corrupted_pdfs'],
                'XMP Metadata': self.stats['xmp_metadata_files'],
                'Word Documents': self.stats['word_documents'],
                'Non-PDF Files': self.stats['non_pdf_files'],
                'Empty Files': self.stats['empty_files'],
                'Missing Files': self.stats['missing_files'],
                'Encrypted': self.stats['encrypted_pdfs'],
                'Size Errors': self.stats['size_errors']
            }
            
            for category, count in categories.items():
                if count > 0:
                    log.info(f"  {category}: {count}")
        
        log.info("=" * 60)

    def save_report(self, report: Dict[str, any]):
        """Save report to file."""
        if not self.report_file:
            return
        
        try:
            with open(self.report_file, 'w') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            log.info(f"Report saved to: {self.report_file}")
        except Exception as e:
            log.error(f"Error saving report: {e}")


def main():
    parser = argparse.ArgumentParser(description="Check PDF file integrity")
    parser.add_argument(
        "--data-dir", type=str, default=str(DATA_DIR),
        help=f"Data directory to check (default: {DATA_DIR})"
    )
    parser.add_argument(
        "--report-file", type=str,
        help="Save detailed report to JSON file"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    data_dir = Path(args.data_dir)
    report_file = Path(args.report_file) if args.report_file else None
    
    checker = PDFIntegrityChecker(data_dir, report_file)
    
    log.info("Starting PDF integrity check")
    
    results = checker.scan_all_files()
    report = checker.generate_report(results)
    
    checker.print_summary()
    checker.save_report(report)
    
    # Exit with error code if issues found
    if len(checker.issues) > 0:
        log.warning(f"Found {len(checker.issues)} files with issues")
        sys.exit(1)
    else:
        log.info("All files are valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
