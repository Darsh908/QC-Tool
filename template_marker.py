"""
QC Tool - Template Marker GUI
Interactive tool for marking fields on packaging design PDFs.
Draw boxes around text regions and assign field names to create reusable templates.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import json
import os

# ─── Preset Field Names ───────────────────────────────────────────────────────
PRESET_FIELDS = [
    "Product Name",
    "Volume",
    "Batch Number",
    "Ingredients",
    "Danger Text",
    "Manufacturer Name",
    "Manufacturer Address",
    "Danger Images",
    "UFI",
    "ECID",
    "Warning Text1",
    "Warning Text2",
    "mg/ml",
    "Barcode Number",
    "Extra Text",
    "QR Code",
]

# ─── Color palette for field boxes ─────────────────────────────────────────────
FIELD_COLORS = {
    "Product Name": "#FF6B6B",
    "Volume": "#4ECDC4",
    "Batch Number": "#45B7D1",
    "Ingredients": "#96CEB4",
    "Danger Text": "#FF4757",
    "Manufacturer Name": "#A55EEA",
    "Manufacturer Address": "#8854D0",
    "Danger Images": "#FD9644",
    "UFI": "#26DE81",
    "ECID": "#2BCBBA",
    "Warning Text1": "#F7B731",
    "Warning Text2": "#FC5C65",
    "mg/ml": "#20BF6B",
    "Barcode Number": "#4B7BEC",
    "Extra Text": "#778CA3",
    "QR Code": "#3867d6",
}
DEFAULT_COLOR = "#778CA3"


def get_field_color(field_name):
    return FIELD_COLORS.get(field_name, DEFAULT_COLOR)


class FieldBox:
    """Represents a single marked field on the PDF."""

    def __init__(self, name, page, x0, y0, x1, y1, field_type="text", ocr_mode=False):
        self.name = name
        self.page = page
        # Store coordinates in PDF space (not canvas space)
        self.x0 = min(x0, x1)
        self.y0 = min(y0, y1)
        self.x1 = max(x0, x1)
        self.y1 = max(y0, y1)
        self.field_type = field_type  # "text" or "image"
        self.ocr_mode = ocr_mode
        # Canvas item IDs (set when drawn)
        self.rect_id = None
        self.label_id = None
        self.label_bg_id = None

    def to_dict(self):
        return {
            "name": self.name,
            "page": self.page,
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
            "type": self.field_type,
            "ocr": self.ocr_mode,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"],
            page=d["page"],
            x0=d["x0"],
            y0=d["y0"],
            x1=d["x1"],
            y1=d["y1"],
            field_type=d.get("type", "text"),
            ocr_mode=d.get("ocr", False),
        )


class TemplateMarkerApp:
    """Main application for marking fields on PDF pages."""

    def __init__(self, root):
        self.root = root
        self.root.title("QC Tool - Template Marker")
        self.root.state("zoomed")  # Maximize window

        # State
        self.pdf_doc = None
        self.pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        self.zoom = 1.5  # Render zoom factor
        self.fields = []  # List of FieldBox
        self.selected_field = None

        # Drawing state
        self.drawing = False
        self.draw_start_x = 0
        self.draw_start_y = 0
        self.temp_rect = None

        # Page dimensions (PDF space)
        self.page_width = 0
        self.page_height = 0

        # Rendered image
        self.tk_image = None

        self._build_ui()
        self._bind_shortcuts()

    # ─── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Main container
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel: canvas area
        left_frame = ttk.Frame(main)
        main.add(left_frame, weight=3)

        # Toolbar
        toolbar = ttk.Frame(left_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text="📂 Open PDF", command=self._open_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="💾 Save Template", command=self._save_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="📁 Load Template", command=self._load_template).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="🗑 Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=2)

        # Zoom controls
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="−", width=3, command=self._zoom_out).pack(side=tk.LEFT, padx=1)
        self.zoom_label = ttk.Label(toolbar, text=f"{int(self.zoom * 100)}%")
        self.zoom_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="+", width=3, command=self._zoom_in).pack(side=tk.LEFT, padx=1)

        # Page navigation
        nav_frame = ttk.Frame(left_frame)
        nav_frame.pack(fill=tk.X, pady=(0, 5))

        self.prev_btn = ttk.Button(nav_frame, text="◀ Previous", command=self._prev_page)
        self.prev_btn.pack(side=tk.LEFT, padx=2)
        self.page_label = ttk.Label(nav_frame, text="No PDF loaded")
        self.page_label.pack(side=tk.LEFT, padx=10)
        self.next_btn = ttk.Button(nav_frame, text="Next ▶", command=self._next_page)
        self.next_btn.pack(side=tk.LEFT, padx=2)

        # Scrollable canvas
        canvas_frame = ttk.Frame(left_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg="#2C2C2C", cursor="crosshair")
        self.v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)

        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Canvas events
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)

        # Right panel: fields list
        right_frame = ttk.Frame(main, width=320)
        main.add(right_frame, weight=1)

        ttk.Label(right_frame, text="📋 Defined Fields", font=("Segoe UI", 12, "bold")).pack(
            anchor=tk.W, padx=5, pady=(5, 2)
        )
        ttk.Label(
            right_frame,
            text="Draw boxes on the PDF to mark fields.\nRight-click a box to edit/delete.",
            foreground="gray",
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, padx=5, pady=(0, 5))

        # Fields listbox with scrollbar
        list_frame = ttk.Frame(right_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.fields_listbox = tk.Listbox(
            list_frame,
            font=("Consolas", 10),
            selectmode=tk.SINGLE,
            bg="#1E1E1E",
            fg="#D4D4D4",
            selectbackground="#264F78",
            selectforeground="#FFFFFF",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor="#007ACC",
        )
        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.fields_listbox.yview)
        self.fields_listbox.configure(yscrollcommand=list_scroll.set)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.fields_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.fields_listbox.bind("<<ListboxSelect>>", self._on_field_select)

        # Action buttons for selected field
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="✏ Edit Name", command=self._edit_selected).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)
        ttk.Button(btn_frame, text="🗑 Delete", command=self._delete_selected).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

        # Field info panel
        self.info_label = ttk.Label(
            right_frame,
            text="",
            font=("Consolas", 9),
            foreground="gray",
            wraplength=300,
            justify=tk.LEFT,
        )
        self.info_label.pack(anchor=tk.W, padx=5, pady=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready — Open a PDF to begin")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _bind_shortcuts(self):
        self.root.bind("<Delete>", lambda e: self._delete_selected())
        self.root.bind("<Control-s>", lambda e: self._save_template())
        self.root.bind("<Control-o>", lambda e: self._open_pdf())
        self.root.bind("<Control-l>", lambda e: self._load_template())
        self.root.bind("<Left>", lambda e: self._prev_page())
        self.root.bind("<Right>", lambda e: self._next_page())
        self.root.bind("<Control-plus>", lambda e: self._zoom_in())
        self.root.bind("<Control-minus>", lambda e: self._zoom_out())
        self.root.bind("<Control-equal>", lambda e: self._zoom_in())

    # ─── PDF Loading & Rendering ──────────────────────────────────────────────

    def _open_pdf(self):
        path = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
        )
        if not path:
            return
        self._load_pdf(path)

    def _load_pdf(self, path):
        try:
            self.pdf_doc = fitz.open(path)
            self.pdf_path = path
            self.total_pages = len(self.pdf_doc)
            self.current_page = 0
            self._render_page()
            self.status_var.set(f"Loaded: {os.path.basename(path)} ({self.total_pages} pages)")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load PDF:\n{e}")

    def _render_page(self):
        if not self.pdf_doc:
            return

        page = self.pdf_doc[self.current_page]
        self.page_width = page.rect.width
        self.page_height = page.rect.height

        # Render page as image
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_image = ImageTk.PhotoImage(img)

        # Update canvas
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))

        # Update page label
        self.page_label.config(text=f"Page {self.current_page + 1} / {self.total_pages}")
        self.prev_btn.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED)

        # Redraw field boxes for this page
        self._redraw_boxes()

    def _prev_page(self):
        if self.pdf_doc and self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def _next_page(self):
        if self.pdf_doc and self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()

    def _zoom_in(self):
        if self.zoom < 5.0:
            self.zoom += 0.25
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")
            self._render_page()

    def _zoom_out(self):
        if self.zoom > 0.5:
            self.zoom -= 0.25
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")
            self._render_page()

    # ─── Coordinate Conversion ────────────────────────────────────────────────

    def _canvas_to_pdf(self, cx, cy):
        """Convert canvas coordinates to PDF space."""
        return cx / self.zoom, cy / self.zoom

    def _pdf_to_canvas(self, px, py):
        """Convert PDF coordinates to canvas space."""
        return px * self.zoom, py * self.zoom

    # ─── Box Drawing ─────────────────────────────────────────────────────────

    def _on_press(self, event):
        if not self.pdf_doc:
            return

        # Get canvas coordinates accounting for scroll
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # Check if clicking an existing box
        clicked_field = self._get_field_at(cx, cy)
        if clicked_field:
            self._select_field(clicked_field)
            return

        # Start drawing a new box
        self.drawing = True
        self.draw_start_x = cx
        self.draw_start_y = cy
        self.selected_field = None
        self._update_fields_list()

    def _on_drag(self, event):
        if not self.drawing:
            return

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # Draw/update temporary rectangle
        if self.temp_rect:
            self.canvas.delete(self.temp_rect)
        self.temp_rect = self.canvas.create_rectangle(
            self.draw_start_x, self.draw_start_y, cx, cy,
            outline="#00FF00", width=2, dash=(5, 3),
        )

    def _on_release(self, event):
        if not self.drawing:
            return
        self.drawing = False

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # Remove temporary rectangle
        if self.temp_rect:
            self.canvas.delete(self.temp_rect)
            self.temp_rect = None

        # Ignore tiny boxes (accidental clicks)
        if abs(cx - self.draw_start_x) < 5 or abs(cy - self.draw_start_y) < 5:
            return

        # Convert to PDF coordinates
        px0, py0 = self._canvas_to_pdf(self.draw_start_x, self.draw_start_y)
        px1, py1 = self._canvas_to_pdf(cx, cy)

        # Ask for field name
        name_info = self._ask_field_name()
        if not name_info:
            return
        
        field_name = name_info["name"]
        use_ocr = name_info["ocr"]

        # Determine type
        field_type = "image" if field_name == "Danger Images" else "text"

        # Create and store field box
        # Create and store field box
        field = FieldBox(field_name, self.current_page, px0, py0, px1, py1, field_type, use_ocr)
        self.fields.append(field)

        # Draw the box
        self._draw_box(field)
        self._update_fields_list()
        self._select_field(field)

        self.status_var.set(f"Added field: {field_name} on page {self.current_page + 1}")

    def _on_right_click(self, event):
        """Right-click on a box to show context menu."""
        if not self.pdf_doc:
            return

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        clicked_field = self._get_field_at(cx, cy)
        if not clicked_field:
            return

        self._select_field(clicked_field)

        # Context menu
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"✏ Edit '{clicked_field.name}'", command=self._edit_selected)
        ocr_label = "Disable OCR" if clicked_field.ocr_mode else "Enable OCR"
        menu.add_command(label=f"👁 {ocr_label}", command=lambda: self._toggle_ocr(clicked_field))
        menu.add_command(label=f"🔄 Change Type ({clicked_field.field_type})", command=lambda: self._toggle_type(clicked_field))
        menu.add_separator()
        menu.add_command(label="🗑 Delete", command=self._delete_selected)
        menu.post(event.x_root, event.y_root)

    def _get_field_at(self, cx, cy):
        """Find which field box contains the given canvas point."""
        px, py = self._canvas_to_pdf(cx, cy)
        for field in reversed(self.fields):
            if field.page == self.current_page:
                if field.x0 <= px <= field.x1 and field.y0 <= py <= field.y1:
                    return field
        return None

    def _ask_field_name(self):
        """Show a dialog to pick or type a field name."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Field Name")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Center on parent
        dialog.geometry("+%d+%d" % (self.root.winfo_x() + 300, self.root.winfo_y() + 200))

        result = {"name": None, "ocr": False}
        
        ocr_var = tk.BooleanVar(value=False)

        ttk.Label(dialog, text="Choose a field name:", font=("Segoe UI", 11)).pack(padx=15, pady=(15, 5))

        # Preset buttons frame
        presets_frame = ttk.Frame(dialog)
        presets_frame.pack(padx=15, pady=5, fill=tk.X)

        # Filter out already-used presets for this page (allow same name on different pages)
        # used_names = {f.name for f in self.fields if f.page == self.current_page}

        row = 0
        col = 0
        for name in PRESET_FIELDS:
            # We now ALLOW duplicate field names as per user request
            state = tk.NORMAL 
            color = get_field_color(name)
            btn = tk.Button(
                presets_frame,
                text=name,
                bg=color,
                fg="white",
                font=("Segoe UI", 9),
                relief=tk.FLAT,
                padx=8,
                pady=3,
                state=state,
                command=lambda n=name: _select(n),
                activebackground=color,
                activeforeground="white",
            )
            btn.grid(row=row, column=col, padx=3, pady=3, sticky=tk.EW)
            col += 1
            if col >= 3:
                col = 0
                row += 1

        # Custom name entry
        ttk.Separator(dialog).pack(fill=tk.X, padx=15, pady=8)
        ttk.Label(dialog, text="Or type a custom name:").pack(padx=15, anchor=tk.W)
        custom_frame = ttk.Frame(dialog)
        custom_frame.pack(padx=15, pady=(2, 15), fill=tk.X)

        custom_entry = ttk.Entry(custom_frame, font=("Segoe UI", 11))
        custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        def _select(name):
            result["name"] = name
            result["ocr"] = ocr_var.get()
            dialog.destroy()

        def _custom_ok():
            name = custom_entry.get().strip()
            if name:
                result["name"] = name
                result["ocr"] = ocr_var.get()
                dialog.destroy()

        ttk.Button(custom_frame, text="OK", command=_custom_ok).pack(side=tk.LEFT)
        custom_entry.bind("<Return>", lambda e: _custom_ok())

        # OCR Option
        ttk.Checkbutton(dialog, text="Use OCR for this field", variable=ocr_var).pack(pady=(5, 10))

        # Cancel
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(pady=(0, 10))

        custom_entry.focus_set()
        self.root.wait_window(dialog)

        return result if result["name"] else None

    # ─── Box Drawing / Rendering ─────────────────────────────────────────────

    def _draw_box(self, field):
        """Draw a field box on the canvas."""
        cx0, cy0 = self._pdf_to_canvas(field.x0, field.y0)
        cx1, cy1 = self._pdf_to_canvas(field.x1, field.y1)
        color = get_field_color(field.name)
        is_selected = field is self.selected_field

        width = 3 if is_selected else 2
        dash = () if is_selected else ()

        # Semi-transparent fill using stipple
        field.rect_id = self.canvas.create_rectangle(
            cx0, cy0, cx1, cy1,
            outline=color,
            width=width,
            dash=dash,
            fill=color,
            stipple="gray12",
        )

        # Label background
        label_text = field.name
        if field.field_type == "image":
            label_text = f"🖼 {field.name}"
        elif field.ocr_mode:
            label_text = f"👁 {field.name}"

        # Calculate label position: above the box if space, else inside top
        label_y = cy0 - 8 if cy0 > 20 else cy0 + 12
        label_x = cx0 + 4

        field.label_bg_id = self.canvas.create_rectangle(
            label_x - 2, label_y - 10, label_x + len(label_text) * 7 + 6, label_y + 4,
            fill=color, outline="",
        )
        field.label_id = self.canvas.create_text(
            label_x + 2, label_y - 3,
            text=label_text,
            anchor=tk.W,
            fill="white",
            font=("Segoe UI", 9, "bold"),
        )

    def _redraw_boxes(self):
        """Redraw all boxes for the current page."""
        for field in self.fields:
            field.rect_id = None
            field.label_id = None
            field.label_bg_id = None
            if field.page == self.current_page:
                self._draw_box(field)

    def _clear_box_drawing(self, field):
        """Remove a field's visual elements from the canvas."""
        for item_id in [field.rect_id, field.label_id, field.label_bg_id]:
            if item_id:
                self.canvas.delete(item_id)
        field.rect_id = None
        field.label_id = None
        field.label_bg_id = None

    # ─── Field Selection & Management ────────────────────────────────────────

    def _select_field(self, field):
        self.selected_field = field
        self._redraw_boxes()
        self._update_fields_list()

        # Show info
        self.info_label.config(
            text=(
                f"Field: {field.name}\n"
                f"Type: {field.field_type} {'(OCR)' if field.ocr_mode else ''}\n"
                f"Page: {field.page + 1}\n"
                f"Coords: ({field.x0:.1f}, {field.y0:.1f}) → ({field.x1:.1f}, {field.y1:.1f})\n"
                f"Size: {field.x1 - field.x0:.1f} × {field.y1 - field.y0:.1f}"
            )
        )

    def _on_field_select(self, event):
        sel = self.fields_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.fields):
            field = self.fields[idx]
            # Navigate to the field's page if needed
            if field.page != self.current_page:
                self.current_page = field.page
                self._render_page()
            self._select_field(field)

    def _update_fields_list(self):
        """Refresh the fields listbox."""
        self.fields_listbox.delete(0, tk.END)
        for i, field in enumerate(self.fields):
            marker = "🖼" if field.field_type == "image" else "📝"
            if field.ocr_mode: marker = "👁"
            prefix = "▸ " if field is self.selected_field else "  "
            self.fields_listbox.insert(
                tk.END,
                f"{prefix}{marker} P{field.page + 1}: {field.name}"
            )
            # Highlight color
            color = get_field_color(field.name)
            self.fields_listbox.itemconfig(i, fg=color)

        # Auto-select
        if self.selected_field and self.selected_field in self.fields:
            idx = self.fields.index(self.selected_field)
            self.fields_listbox.selection_set(idx)
            self.fields_listbox.see(idx)

    def _edit_selected(self):
        if not self.selected_field:
            messagebox.showinfo("Info", "No field selected. Click a box or select from the list.")
            return

        new_info = self._ask_field_name()
        if new_info:
            self.selected_field.name = new_info["name"]
            self.selected_field.ocr_mode = new_info["ocr"]
            self.selected_field.field_type = "image" if new_info["name"] == "Danger Images" else "text"
            self._render_page()
            self._update_fields_list()
            self._select_field(self.selected_field)
            self.status_var.set(f"Renamed field to: {new_info['name']}")

    def _delete_selected(self):
        if not self.selected_field:
            messagebox.showinfo("Info", "No field selected. Click a box or select from the list.")
            return

        name = self.selected_field.name
        self._clear_box_drawing(self.selected_field)
        self.fields.remove(self.selected_field)
        self.selected_field = None
        self._update_fields_list()
        self.info_label.config(text="")
        self.status_var.set(f"Deleted field: {name}")

    def _toggle_type(self, field):
        field.field_type = "image" if field.field_type == "text" else "text"
        self._render_page()
        self._update_fields_list()
        self.status_var.set(f"Changed '{field.name}' type to: {field.field_type}")

    def _toggle_ocr(self, field):
        field.ocr_mode = not field.ocr_mode
        self._render_page()
        self._update_fields_list()
        status = "Enabled" if field.ocr_mode else "Disabled"
        self.status_var.set(f"{status} OCR for '{field.name}'")

    def _clear_all(self):
        if not self.fields:
            return
        if messagebox.askyesno("Confirm", "Delete all field boxes?"):
            for field in self.fields:
                self._clear_box_drawing(field)
            self.fields.clear()
            self.selected_field = None
            self._update_fields_list()
            self.info_label.config(text="")
            self._render_page()
            self.status_var.set("All fields cleared")

    # ─── Template Save / Load ────────────────────────────────────────────────

    def _save_template(self):
        if not self.fields:
            messagebox.showwarning("Warning", "No fields defined. Draw boxes on the PDF first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Template",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialfile="template.json",
        )
        if not path:
            return

        template = {
            "pdf_name": os.path.basename(self.pdf_path) if self.pdf_path else "",
            "page_width": self.page_width,
            "page_height": self.page_height,
            "total_pages": self.total_pages,
            "fields": [f.to_dict() for f in self.fields],
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
            self.status_var.set(f"Template saved: {os.path.basename(path)} ({len(self.fields)} fields)")
            messagebox.showinfo("Success", f"Template saved with {len(self.fields)} fields.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save template:\n{e}")

    def _load_template(self):
        path = filedialog.askopenfilename(
            title="Load Template",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                template = json.load(f)

            # Clear existing fields
            self.fields.clear()
            self.selected_field = None

            # Load fields
            for fd in template.get("fields", []):
                field = FieldBox.from_dict(fd)
                self.fields.append(field)

            self._update_fields_list()

            if self.pdf_doc:
                self._render_page()

            self.status_var.set(
                f"Template loaded: {os.path.basename(path)} ({len(self.fields)} fields)"
            )
            messagebox.showinfo("Success", f"Loaded {len(self.fields)} fields from template.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load template:\n{e}")


def main():
    root = tk.Tk()
    app = TemplateMarkerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
