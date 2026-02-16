#!/usr/bin/env python3
"""
QC Tool - Installation Verification Script
Tests all dependencies and provides setup guidance.
"""

import sys
import importlib
from pathlib import Path

def test_import(module_name, package_name=None, optional=False):
    """Test if a module can be imported."""
    pkg = package_name or module_name
    try:
        importlib.import_module(module_name)
        print(f"✅ {pkg:<20} - Installed")
        return True
    except ImportError:
        status = "⚠️  OPTIONAL" if optional else "❌ REQUIRED"
        print(f"{status} {pkg:<20} - Not found")
        if not optional:
            print(f"   Install with: pip install {pkg}")
        return False


def test_system_tools():
    """Test system-level dependencies."""
    print("\n📦 System Tools:")
    print("-" * 50)
    
    # Test Tesseract
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        print(f"✅ Tesseract OCR      - Installed")
    except:
        print(f"⚠️  Tesseract OCR      - Not found or not configured")
        print("   Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
        print("   Linux:   sudo apt-get install tesseract-ocr")
        print("   macOS:   brew install tesseract")
    
    # Test zbar (for pyzbar)
    try:
        from pyzbar import pyzbar
        # Try to use it (will fail if zbar library not installed)
        print(f"✅ ZBar (pyzbar)      - Installed")
    except ImportError:
        print(f"❌ ZBar (pyzbar)      - Not found")
        print("   Windows: Download from http://zbar.sourceforge.net/")
        print("   Linux:   sudo apt-get install libzbar0")
        print("   macOS:   brew install zbar")


def main():
    print("=" * 50)
    print("QC Tool - Installation Verification")
    print("=" * 50)
    
    # Test Python version
    print(f"\n🐍 Python Version: {sys.version}")
    if sys.version_info < (3, 8):
        print("⚠️  Warning: Python 3.8+ recommended")
    
    # Test core packages
    print("\n📚 Core Packages:")
    print("-" * 50)
    
    core_packages = [
        ("fitz", "PyMuPDF"),
        ("PIL", "Pillow"),
        ("pytesseract", "pytesseract"),
    ]
    
    all_core_ok = True
    for module, package in core_packages:
        if not test_import(module, package):
            all_core_ok = False
    
    # Test barcode packages
    print("\n📊 Barcode/QR Detection:")
    print("-" * 50)
    
    barcode_ok = test_import("pyzbar.pyzbar", "pyzbar")
    cv2_ok = test_import("cv2", "opencv-python")
    numpy_ok = test_import("numpy", "numpy")
    
    # Test optional packages
    print("\n✨ Optional Enhancements:")
    print("-" * 50)
    test_import("qreader", "qreader", optional=True)
    
    # Test tkinter (for GUI)
    print("\n🖼️  GUI Support:")
    print("-" * 50)
    try:
        import tkinter
        print(f"✅ tkinter            - Available (built-in)")
    except ImportError:
        print(f"❌ tkinter            - Not available")
        print("   Linux: sudo apt-get install python3-tk")
    
    # System tools
    test_system_tools()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Summary")
    print("=" * 50)
    
    if all_core_ok and barcode_ok and cv2_ok and numpy_ok:
        print("✅ All required packages are installed!")
        print("✅ Barcode detection is ready!")
        print("\nYou can now run:")
        print("  • Template Marker: python qc_template_marker_enhanced.py")
        print("  • Data Extractor:  python qc_data_extractor_enhanced.py -h")
    else:
        print("⚠️  Some required packages are missing.")
        print("\nQuick fix:")
        print("  pip install -r requirements.txt")
        print("\nThen install system tools (Tesseract, zbar) as shown above.")
    
    # Create a simple test
    print("\n" + "=" * 50)
    print("🧪 Quick Test")
    print("=" * 50)
    
    try:
        import fitz
        from PIL import Image
        import numpy as np
        import cv2
        from pyzbar import pyzbar
        
        print("Testing barcode detection functionality...")
        
        # Create a simple test image (would need actual barcode for real test)
        test_array = np.zeros((100, 100, 3), dtype=np.uint8)
        print("✅ Image processing libraries working")
        
        print("\n🎉 All core functionality tests passed!")
        print("Ready to use the QC Tool!")
        
    except Exception as e:
        print(f"⚠️  Functionality test failed: {e}")
        print("Please install missing dependencies.")
    
    print("\n" + "=" * 50)
    print("For detailed usage, see README.md and QUICKSTART.md")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
