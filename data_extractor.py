"""
QC Tool - Data Extractor
Extracts text and detects images from PDF pages using a saved template.
Outputs structured JSON with per-page, per-field results.
"""

import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import cv2
import numpy as np
import io
import json
import argparse
import os
from datetime import datetime


def load_template(template_path):
    """Load a template JSON file."""
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_text_from_rect(page, rect):
    """Extract text from a rectangular region on a PDF page."""
    clip = fitz.Rect(rect)
    text = page.get_text("text", clip=clip).strip()
    return text


def preprocess_image_for_ocr(image):
    """
    Apply advanced preprocessing to improve OCR accuracy.
    Handles colored text, fancy fonts, and noise.
    """
    # Convert to OpenCV format
    img_array = np.array(image)
    
    # Check if image is loaded properly
    if img_array.size == 0:
        return image

    # Convert to grayscale
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # Adaptive Thresholding (handling varying lighting/shadows/colors)
    # This works well for text on colored backgrounds
    processed = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )

    # Denoising (optional, might remove dots in text)
    processed = cv2.fastNlMeansDenoising(processed, None, 10, 7, 21)

    return Image.fromarray(processed)


def extract_text_via_ocr(page, rect):
    """Extract text from a rectangular region using OCR (Tesseract)."""
    # Get pixmap of the region
    clip = fitz.Rect(rect)
    # High resolution for better OCR (increase zoom factor)
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip)
    
    # Convert to PIL Image
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    
    # Advanced Preprocessing
    try:
        image = preprocess_image_for_ocr(image)
    except Exception as e:
        print(f"Warning: Preprocessing failed: {e}")
        image = image.convert("L")  # Fallback to simple grayscale
    
    # Run OCR with custom configuration
    # --psm 6 assumes a single uniform block of text
    try:
        custom_config = r'--oem 3 --psm 6'
        # pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        text = pytesseract.image_to_string(image, config=custom_config).strip()
        return text
    except Exception as e:
        return f"[OCR Failed: {str(e)}]"


def scan_barcode_qr(page, rect):
    """Scan for Barcodes or QR codes in the region using multiple preprocessing passes."""
    clip = fitz.Rect(rect)
    results = []
    
    # We will try multiple zoom levels: 3x (Standard), 5x (High-Res for small codes)
    for zoom in [3, 5]:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
        img_data = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_data))
        img_array = np.array(image.convert("RGB"))
        
        # OpenCV uses BGR
        bgr_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
        
        # CLAHE (Contrast Enhancement) - helps with colorful/busy backgrounds
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        
        # Preprocessing versions to try
        processing_variants = [
            ("original", bgr_img),
            ("grayscale", gray),
            ("clahe", gray_clahe),
            ("threshold", cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)[1]),
            ("adaptive", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)),
            ("inverted", cv2.bitwise_not(gray)),
            ("inverted_threshold", cv2.threshold(cv2.bitwise_not(gray), 128, 255, cv2.THRESH_BINARY)[1])
        ]
        
        qr_detector = cv2.QRCodeDetector()
        barcode_detector = None
        try:
            barcode_detector = cv2.barcode.BarcodeDetector()
        except:
            pass

        for name, img in processing_variants:
            # 1. Try QR detection
            try:
                # Returns (decoded_info, points, straight_qrcode) in most modern OpenCV
                res_qr = qr_detector.detectAndDecode(img)
                if res_qr and isinstance(res_qr, tuple) and res_qr[0]:
                    results.append(f"[QR] {res_qr[0]}")
            except Exception:
                pass
                
            # 2. Try Barcode detection
            if barcode_detector:
                try:
                    # Returns (decoded_info, decoded_type, points)
                    res_bc = barcode_detector.detectAndDecode(img)
                    if res_bc and isinstance(res_bc, tuple) and res_bc[0]:
                        info_list = res_bc[0]
                        type_list = res_bc[1]
                        # Handle both single results and multi-results
                        if isinstance(info_list, str):
                            if info_list:
                                results.append(f"[{type_list}] {info_list}")
                        else:
                            for info, btype in zip(info_list, type_list):
                                if info:
                                    results.append(f"[{btype}] {info}")
                except Exception:
                    pass
            
            if results: break # Found something at this zoom/processing level
        if results: break
        
    return list(set(results))  # Unique results


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
            elif "barcode" in field_name.lower() or "qr" in field_name.lower():
                # Automatic Barcode/QR scanning
                codes = scan_barcode_qr(page, rect)
                value = ", ".join(codes) if codes else "No code found"
                result_data = {
                    "value": value,
                    "confidence": "scanned" if codes else "empty",
                    "type": "barcode_qr",
                    "method": "pyzbar",
                    "codes": codes,
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
                elif ftype == "barcode_qr":
                    icon = "📷"
                    status = "✅" if field_data["codes"] else "❌"
                    print(f"  {icon} {field_name}{suffix}: {status} {value}")
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
        description="QC Tool - Extract text data from PDF using a template"
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
