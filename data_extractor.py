"""
QC Tool - Data Extractor
Extracts text, detects images, and decodes barcodes/QR codes from PDF pages using a saved template.
Outputs structured JSON with per-page, per-field results.
"""

import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io
import json
import argparse
import os
from datetime import datetime
import cv2
import numpy as np

# Barcode/QR code libraries
try:
    from pyzbar import pyzbar
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    print("Warning: pyzbar not installed. Barcode/QR detection will be limited.")

try:
    from qreader import QReader
    QREADER_AVAILABLE = True
except ImportError:
    QREADER_AVAILABLE = False


def load_template(template_path):
    """Load a template JSON file."""
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_text_from_rect(page, rect):
    """Extract text from a rectangular region on a PDF page."""
    clip = fitz.Rect(rect)
    text = page.get_text("text", clip=clip).strip()
    return text


def extract_text_via_ocr(page, rect):
    """Extract text from a rectangular region using OCR (Tesseract)."""
    # Get pixmap of the region
    clip = fitz.Rect(rect)
    # High resolution for better OCR
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip)
    
    # Convert to PIL Image
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    
    # Run OCR
    try:
        # pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        text = pytesseract.image_to_string(image).strip()
        return text
    except Exception as e:
        return f"[OCR Failed: {str(e)}]"


def check_images_in_rect(page, rect):
    """Check if there are images overlapping with the given rectangle region."""
    target_rect = fitz.Rect(rect)
    image_count = 0
    image_list = page.get_images(full=True)

    for img_info in image_list:
        xref = img_info[0]
        # Get all instances of this image on the page
        img_rects = page.get_image_rects(xref)
        for img_rect in img_rects:
            # Check if image rectangle intersects with our target region
            if img_rect.intersects(target_rect):
                image_count += 1

    return image_count > 0, image_count


def decode_barcodes_and_qr(page, rect):
    """
    Decode barcodes and QR codes from a rectangular region on a PDF page.
    
    Returns:
        dict: Contains decoded data, type, and success status
    """
    clip = fitz.Rect(rect)
    # High resolution for better detection
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip)
    
    # Convert to numpy array for OpenCV
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    img_array = np.array(image)
    
    results = {
        "decoded": False,
        "codes": [],
        "method": None,
        "error": None
    }
    
    # Method 1: Try pyzbar (works for most barcodes and QR codes)
    if PYZBAR_AVAILABLE:
        try:
            decoded_objects = pyzbar.decode(img_array)
            if decoded_objects:
                results["decoded"] = True
                results["method"] = "pyzbar"
                for obj in decoded_objects:
                    code_data = {
                        "type": obj.type,
                        "data": obj.data.decode('utf-8'),
                        "quality": "good",
                        "rect": {
                            "x": obj.rect.left,
                            "y": obj.rect.top,
                            "width": obj.rect.width,
                            "height": obj.rect.height
                        }
                    }
                    results["codes"].append(code_data)
                return results
        except Exception as e:
            results["error"] = f"pyzbar error: {str(e)}"
    
    # Method 2: Try OpenCV QR code detector (backup for QR codes)
    if not results["decoded"]:
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # Try QR code detection with OpenCV
            qr_detector = cv2.QRCodeDetector()
            data, bbox, _ = qr_detector.detectAndDecode(gray)
            
            if data:
                results["decoded"] = True
                results["method"] = "opencv_qr"
                results["codes"].append({
                    "type": "QRCODE",
                    "data": data,
                    "quality": "opencv"
                })
                return results
        except Exception as e:
            if results["error"]:
                results["error"] += f"; opencv error: {str(e)}"
            else:
                results["error"] = f"opencv error: {str(e)}"
    
    # Method 3: Try QReader for QR codes (if available)
    if not results["decoded"] and QREADER_AVAILABLE:
        try:
            qreader = QReader()
            decoded_text = qreader.detect_and_decode(image=img_array)
            if decoded_text and decoded_text[0]:
                results["decoded"] = True
                results["method"] = "qreader"
                for text in decoded_text:
                    if text:
                        results["codes"].append({
                            "type": "QRCODE",
                            "data": text,
                            "quality": "qreader"
                        })
                return results
        except Exception as e:
            if results["error"]:
                results["error"] += f"; qreader error: {str(e)}"
            else:
                results["error"] = f"qreader error: {str(e)}"
    
    # Method 4: Try preprocessing and retry with pyzbar
    if not results["decoded"] and PYZBAR_AVAILABLE:
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # Apply preprocessing
            # 1. Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # 2. Adaptive thresholding
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 11, 2
            )
            
            # Try decoding preprocessed image
            decoded_objects = pyzbar.decode(thresh)
            if decoded_objects:
                results["decoded"] = True
                results["method"] = "pyzbar_preprocessed"
                for obj in decoded_objects:
                    results["codes"].append({
                        "type": obj.type,
                        "data": obj.data.decode('utf-8'),
                        "quality": "preprocessed"
                    })
                return results
        except Exception as e:
            if results["error"]:
                results["error"] += f"; preprocessing error: {str(e)}"
            else:
                results["error"] = f"preprocessing error: {str(e)}"
    
    if not results["decoded"]:
        results["error"] = results["error"] or "No barcode or QR code detected in region"
    
    return results


def extract_data_from_pdf(pdf_path, template, pages=None):
    """
    Extract data from a PDF using the template.
    
    Args:
        pdf_path: Path to the PDF file to extract from
        template: Loaded template dictionary
        pages: Optional list of page numbers to extract (0-indexed). 
               If None, extracts from all pages.
    
    Returns:
        Dictionary with extraction results
    """
    doc = fitz.open(pdf_path)
    
    template_page_width = template.get("page_width", 0)
    template_page_height = template.get("page_height", 0)
    
    results = {
        "source_pdf": os.path.basename(pdf_path),
        "template_used": template.get("pdf_name", "unknown"),
        "extraction_date": datetime.now().isoformat(),
        "total_pages": len(doc),
        "pages": []
    }
    
    # Determine which pages to process
    pages_to_process = pages if pages else list(range(len(doc)))
    
    for page_num in pages_to_process:
        if page_num >= len(doc):
            continue
            
        page = doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height
        
        # Calculate scale factors if PDF dimensions differ from template
        scale_x = page_width / template_page_width if template_page_width > 0 else 1.0
        scale_y = page_height / template_page_height if template_page_height > 0 else 1.0
        
        page_result = {
            "page_number": page_num + 1,
            "page_dimensions": {
                "width": page_width,
                "height": page_height
            },
            "fields": {}
        }
        
        for field_def in template.get("fields", []):
            field_name = field_def["name"]
            field_type = field_def.get("type", "text")
            ocr_mode = field_def.get("ocr", False)
            
            # Scale coordinates to match actual PDF dimensions
            x0 = field_def["x0"] * scale_x
            y0 = field_def["y0"] * scale_y
            x1 = field_def["x1"] * scale_x
            y1 = field_def["y1"] * scale_y
            rect = (x0, y0, x1, y1)
            
            if field_type == "image":
                has_images, count = check_images_in_rect(page, rect)
                result_data = {
                    "value": f"{count} image(s) found" if has_images else "No images found",
                    "has_images": has_images,
                    "image_count": count,
                    "type": "image",
                    "coordinates": {"x0": round(x0, 2), "y0": round(y0, 2),
                                    "x1": round(x1, 2), "y1": round(y1, 2)}
                }
            elif field_type == "barcode":
                # Barcode/QR code detection
                decode_result = decode_barcodes_and_qr(page, rect)
                
                if decode_result["decoded"]:
                    # Format the decoded data
                    codes_summary = []
                    for code in decode_result["codes"]:
                        codes_summary.append(f"{code['type']}: {code['data']}")
                    
                    result_data = {
                        "value": " | ".join(codes_summary) if codes_summary else "No code detected",
                        "decoded": decode_result["decoded"],
                        "codes": decode_result["codes"],
                        "method": decode_result["method"],
                        "type": "barcode",
                        "coordinates": {"x0": round(x0, 2), "y0": round(y0, 2),
                                        "x1": round(x1, 2), "y1": round(y1, 2)}
                    }
                else:
                    result_data = {
                        "value": "No code detected",
                        "decoded": False,
                        "error": decode_result.get("error", "Unknown error"),
                        "type": "barcode",
                        "coordinates": {"x0": round(x0, 2), "y0": round(y0, 2),
                                        "x1": round(x1, 2), "y1": round(y1, 2)}
                    }
            else:
                # Text extraction (Digital or OCR)
                if ocr_mode:
                    text = extract_text_via_ocr(page, rect)
                    method = "ocr"
                else:
                    text = extract_text_from_rect(page, rect)
                    method = "digital"
                
                result_data = {
                    "value": text,
                    "confidence": "extracted" if text else "empty",
                    "type": "text",
                    "method": method,
                    "coordinates": {"x0": round(x0, 2), "y0": round(y0, 2),
                                    "x1": round(x1, 2), "y1": round(y1, 2)}
                }

            # Append to list of values for this field name
            if field_name not in page_result["fields"]:
                page_result["fields"][field_name] = []
            page_result["fields"][field_name].append(result_data)
        
        results["pages"].append(page_result)
    
    doc.close()
    return results


def print_summary(results):
    """Print a human-readable summary of extracted data."""
    print("\n" + "=" * 70)
    print(f"  QC Data Extraction Report")
    print(f"  PDF: {results['source_pdf']}")
    print(f"  Template: {results['template_used']}")
    print(f"  Date: {results['extraction_date']}")
    print(f"  Total Pages: {results['total_pages']}")
    print("=" * 70)
    
    for page_data in results["pages"]:
        print(f"\n{'─' * 50}")
        print(f"  Page {page_data['page_number']}")
        print(f"{'─' * 50}")
        
        for field_name, field_values in page_data["fields"].items():
            # field_values is now a LIST
            for i, field_data in enumerate(field_values):
                value = field_data["value"]
                ftype = field_data["type"]
                suffix = f" (#{i+1})" if len(field_values) > 1 else ""
                
                if ftype == "image":
                    icon = "🖼"
                    status = "✅" if field_data["has_images"] else "❌"
                    print(f"  {icon} {field_name}{suffix}: {status} {value}")
                elif ftype == "barcode":
                    icon = "📊"
                    if field_data.get("decoded", False):
                        status = "✅ DECODED"
                        print(f"  {icon} {field_name}{suffix}: {status}")
                        print(f"       → {value}")
                        print(f"       → Method: {field_data.get('method', 'unknown')}")
                        # Show individual codes if multiple
                        if "codes" in field_data and len(field_data["codes"]) > 1:
                            for code in field_data["codes"]:
                                print(f"          • {code['type']}: {code['data']}")
                    else:
                        status = "❌ NOT DETECTED"
                        print(f"  {icon} {field_name}{suffix}: {status}")
                        if "error" in field_data:
                            print(f"       → Error: {field_data['error']}")
                else:
                    icon = "📝"
                    method = field_data.get("method", "digital")
                    icon = "👁" if method == "ocr" else "📝"
                    
                    # Truncate long values for display
                    display_val = value[:80] + "..." if len(value) > 80 else value
                    display_val = display_val.replace("\n", " | ")
                    status = "✅" if value else "⚠️ EMPTY"
                    print(f"  {icon} {field_name}{suffix}: {status}")
                    if value:
                        print(f"       → {display_val}")
    
    print(f"\n{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="QC Tool - Extract text data and decode barcodes/QR codes from PDF using a template"
    )
    parser.add_argument(
        "--template", "-t",
        required=True,
        help="Path to the template JSON file"
    )
    parser.add_argument(
        "--pdf", "-p",
        required=True,
        help="Path to the PDF file to extract data from"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for the output JSON file (default: extracted_data.json)"
    )
    parser.add_argument(
        "--pages",
        type=str,
        default=None,
        help="Comma-separated page numbers to extract (1-indexed). Default: all pages. Example: 1,3,5"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress console output summary"
    )
    
    args = parser.parse_args()
    
    # Check library availability
    if not PYZBAR_AVAILABLE:
        print("\n⚠️  Warning: pyzbar library not found!")
        print("   Barcode/QR detection will be limited or may not work.")
        print("   Install with: pip install pyzbar")
        print("   (Note: You may also need to install zbar system library)\n")
    
    # Validate inputs
    if not os.path.exists(args.template):
        print(f"Error: Template file not found: {args.template}")
        return 1
    if not os.path.exists(args.pdf):
        print(f"Error: PDF file not found: {args.pdf}")
        return 1
    
    # Parse page numbers if provided
    page_list = None
    if args.pages:
        try:
            page_list = [int(p.strip()) - 1 for p in args.pages.split(",")]
        except ValueError:
            print("Error: Invalid page numbers. Use comma-separated integers (e.g., 1,3,5)")
            return 1
    
    # Load template
    template = load_template(args.template)
    print(f"Loaded template with {len(template.get('fields', []))} fields")
    
    # Extract data
    results = extract_data_from_pdf(args.pdf, template, page_list)
    
    # Output path
    output_path = args.output or "extracted_data.json"
    
    # Save JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Data saved to: {output_path}")
    
    # Print summary
    if not args.quiet:
        print_summary(results)
    
    return 0


if __name__ == "__main__":
    exit(main())
