# =============================================================================
# REPLACES the old _render_certificate_pdf function in app.py.
#
# SETUP REQUIRED:
#   1. Put certificate_template.pdf in: static/certificates/certificate_template.pdf
#      (the file is provided alongside this snippet — it's your uploaded
#      "Certificate of Achievement" design, used as-is)
#   2. pip install pypdf --break-system-packages   (reportlab is already required)
#
# This keeps your exact template (background art, gold seal, "Founder,
# CareerOS" signature line, borders) untouched, and overlays only the three
# dynamic fields — learner name, course title, issued date — plus a small
# verification code line at the very bottom for authenticity checks.
#
# FIX (this version): the issued-date y-coordinate was wrong (page_h - 488),
# which put the date ~40pt below the "[Date]" placeholder instead of on it.
# The correct box was measured directly from the template PDF with
# pdfplumber: "[Date]" sits at x0=593.7 x1=630.8 top=435.7 bottom=447.4
# (top-down coords, page height 595.5). We now also paint a small
# background-colored rectangle over the literal "[Date]" text before
# drawing the real date, so the placeholder text doesn't show through.
# =============================================================================

CERTIFICATE_TEMPLATE_PATH = os.path.join('static', 'certificates', 'certificate_template.pdf')


def _render_certificate_pdf(user, course_title, domain, certificate_code, issued_at):
    """
    Overlays the learner's name, course title, and issue date onto the
    CareerOS certificate template PDF and returns the merged PDF as bytes.
    """
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdfcanvas

    reader = PdfReader(CERTIFICATE_TEMPLATE_PATH)
    template_page = reader.pages[0]
    page_w = float(template_page.mediabox.width)
    page_h = float(template_page.mediabox.height)

    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(page_w, page_h))

    cyan = HexColor("#37D6F0")
    white = HexColor("#EAF6FB")
    muted = HexColor("#9fd3e0")
    bg = HexColor("#090E20")  # sampled from the template's background near the date field
    center_x = page_w / 2

    # ── Learner name (fills the "[LEARNER NAME]" placeholder) ──
    name = user.name or "CareerOS Learner"
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(cyan)
    # shrink automatically if the name is long, so it never overflows the underline
    name_font_size = 26
    while c.stringWidth(name, "Helvetica-Bold", name_font_size) > 380 and name_font_size > 14:
        name_font_size -= 1
        c.setFont("Helvetica-Bold", name_font_size)
    c.drawCentredString(center_x, page_h - 245.9 + 7, name)

    # ── Course title (fills the "course: [Course Name]" placeholder) ──
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(white)
    max_w = 560
    if c.stringWidth(course_title, "Helvetica-Bold", 15) > max_w:
        words = course_title.split()
        line1, line2 = "", ""
        for w in words:
            trial = (line1 + " " + w).strip()
            if c.stringWidth(trial, "Helvetica-Bold", 15) <= max_w:
                line1 = trial
            else:
                line2 = (line2 + " " + w).strip()
        c.drawCentredString(center_x, page_h - 326.7 + 4 + 9, line1)
        c.drawCentredString(center_x, page_h - 326.7 + 4 - 9, line2)
    else:
        c.drawCentredString(center_x, page_h - 326.7 + 4, course_title)

    # ── Issued date (fills the "[Date]" placeholder) ──
    # Placeholder text box measured directly from the template PDF via pdfplumber:
    #   "[Date]"  x0=593.7  x1=630.8  top=435.7  bottom=447.4  (top-down coords)
    date_box_x0, date_box_x1 = 593.7, 630.8
    date_box_top, date_box_bottom = 435.7, 447.4  # top-down (measured from page top)

    # cover the literal "[Date]" placeholder text with the template's background
    # color before drawing the real date over it, so the placeholder text
    # doesn't show through underneath the new value
    cover_pad = 8
    cover_x0 = date_box_x0 - cover_pad
    cover_x1 = date_box_x1 + cover_pad
    cover_y_bottom = (page_h - date_box_bottom) - 3
    cover_y_top = (page_h - date_box_top) + 3
    c.setFillColor(bg)
    c.rect(cover_x0, cover_y_bottom, cover_x1 - cover_x0, cover_y_top - cover_y_bottom, stroke=0, fill=1)

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(white)
    date_center_x = (date_box_x0 + date_box_x1) / 2
    date_baseline_y = (page_h - date_box_bottom) + 2  # baseline ≈ bottom of glyphs + small descender offset
    c.drawCentredString(date_center_x, date_baseline_y, issued_at.strftime("%d %b %Y"))

    # ── Verification code footer ──
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawCentredString(center_x, 18, f"Verification Code: {certificate_code}")

    c.showPage()
    c.save()
    buf.seek(0)

    overlay_reader = PdfReader(buf)
    writer = PdfWriter()
    template_page.merge_page(overlay_reader.pages[0])
    writer.add_page(template_page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
