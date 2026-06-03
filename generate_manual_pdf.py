"""
generate_manual_pdf.py  —  TrintzPOS User Manual PDF generator
Uses reportlab. Run: python generate_manual_pdf.py
"""

import os, re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, HRFlowable, PageBreak,
    Table, TableStyle, NextPageTemplate,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# ── Palette ───────────────────────────────────────────────────────────────────
BRAND_DARK   = colors.HexColor('#0f2744')
BRAND_MID    = colors.HexColor('#1e3a6e')
BRAND_ACCENT = colors.HexColor('#4f8ef7')
SECTION_BG   = colors.HexColor('#eef3fb')
CODE_BG      = colors.HexColor('#f4f4f4')
TEXT_DARK    = colors.HexColor('#1a1a2e')
BORDER_CLR   = colors.HexColor('#c8d8f0')
HR_CLR       = colors.HexColor('#d0dff8')
WHITE        = colors.white

W, H = A4          # 595.28 x 841.89 pts
MARGIN = 20 * mm   # content margin for inner pages

# ── Styles ────────────────────────────────────────────────────────────────────
SS = getSampleStyleSheet()

def sty(name, base='Normal', **kw):
    p = ParagraphStyle(name, parent=SS[base], **kw)
    SS.add(p)
    return p

BODY  = sty('MBody',  fontSize=9.5, leading=14, textColor=TEXT_DARK,
            spaceAfter=2, alignment=TA_JUSTIFY)
BULL  = sty('MBull',  fontSize=9.5, leading=13, textColor=TEXT_DARK,
            leftIndent=12, spaceAfter=1)
CODE  = sty('MCode',  fontSize=8.5, leading=12, textColor=colors.HexColor('#1a3060'),
            fontName='Courier', leftIndent=8, backColor=CODE_BG, spaceAfter=1)
FAQQ  = sty('MFAQQ',  fontSize=9.5, leading=13, textColor=BRAND_MID,
            fontName='Helvetica-Bold', spaceAfter=2, spaceBefore=6)
FAQA  = sty('MFAQA',  fontSize=9.5, leading=13, textColor=TEXT_DARK,
            leftIndent=8, spaceAfter=4)

# ── Canvas-drawn decorations ──────────────────────────────────────────────────
def draw_cover(canvas, doc):
    """Draw the cover page using raw canvas calls."""
    canvas.saveState()

    # Gradient background via stacked strips
    steps = 80
    for i in range(steps):
        r_val = int(0x0f + (0x1e - 0x0f) * i / steps)
        g_val = int(0x27 + (0x3a - 0x27) * i / steps)
        b_val = int(0x44 + (0x6e - 0x44) * i / steps)
        canvas.setFillColorRGB(r_val/255, g_val/255, b_val/255)
        canvas.rect(0, i * H/steps, W, H/steps + 1, fill=1, stroke=0)

    # Decorative translucent circles
    for (cx, cy, r, alpha) in [
        (W*0.85, H*0.78, 110, 0.05),
        (W*0.10, H*0.20,  80, 0.04),
        (W*0.50, H*0.92, 170, 0.03),
    ]:
        canvas.setFillColorRGB(1, 1, 1, alpha)
        canvas.circle(cx, cy, r, fill=1, stroke=0)

    # Top accent stripe
    canvas.setFillColor(colors.HexColor('#4f8ef7'))
    canvas.rect(0, H - 5, W, 5, fill=1, stroke=0)

    # Logo card
    card_x, card_y = MARGIN, H * 0.63
    card_w, card_h = W - 2*MARGIN, 95
    canvas.setFillColor(colors.HexColor('#ffffff15'))
    canvas.roundRect(card_x, card_y, card_w, card_h, 10, fill=1, stroke=0)

    # App name
    canvas.setFont('Helvetica-Bold', 36)
    canvas.setFillColor(WHITE)
    canvas.drawCentredString(W/2, H*0.73, 'TrintzPOS')

    canvas.setFont('Helvetica', 13)
    canvas.setFillColor(colors.HexColor('#b8d0f8'))
    canvas.drawCentredString(W/2, H*0.69, 'Complete User & System Manual')

    # Divider
    canvas.setStrokeColor(colors.HexColor('#4f8ef7'))
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN*3, H*0.60, W - MARGIN*3, H*0.60)

    # Version meta
    canvas.setFont('Helvetica', 10)
    canvas.setFillColor(colors.HexColor('#90aad4'))
    canvas.drawCentredString(W/2, H*0.565, 'Version 1.0  |  May 2026  |  by Trintz Data Labs')

    # Feature pills
    pills = ['GST Compliant', 'Multi-User', 'AI Powered', 'RAG Knowledge Base']
    pill_w, pill_h, gap = 88, 20, 10
    total = len(pills) * pill_w + (len(pills)-1) * gap
    sx = (W - total) / 2
    for j, label in enumerate(pills):
        px = sx + j*(pill_w + gap)
        py = H * 0.44
        canvas.setFillColor(colors.HexColor('#1a4a8a'))
        canvas.roundRect(px, py, pill_w, pill_h, 7, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#7ab3f8'))
        canvas.setFont('Helvetica', 8)
        canvas.drawCentredString(px + pill_w/2, py + 6, label)

    # Stat badges
    badges = [('30', 'Sections'), ('80+', 'API Endpoints'), ('22', 'DB Tables'), ('30', 'FAQs')]
    bw = (W - 2*MARGIN - 30) / 4
    for j, (num, lbl) in enumerate(badges):
        bx = MARGIN + j*(bw + 10)
        by = H * 0.31
        canvas.setFillColor(colors.HexColor('#ffffff10'))
        canvas.roundRect(bx, by, bw, 52, 8, fill=1, stroke=0)
        canvas.setFont('Helvetica-Bold', 20)
        canvas.setFillColor(colors.HexColor('#4f8ef7'))
        canvas.drawCentredString(bx + bw/2, by + 28, num)
        canvas.setFont('Helvetica', 8.5)
        canvas.setFillColor(colors.HexColor('#90aad4'))
        canvas.drawCentredString(bx + bw/2, by + 14, lbl)

    # Bottom bar
    canvas.setFillColor(colors.HexColor('#0a1c35'))
    canvas.rect(0, 0, W, 26, fill=1, stroke=0)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#6090c0'))
    canvas.drawCentredString(W/2, 9,
        'Confidential — For internal use only  |  Trintz Data Labs')

    canvas.restoreState()


def draw_page(canvas, doc):
    """Header + footer on every content page."""
    canvas.saveState()
    pg = canvas.getPageNumber() - 1   # cover=page1, so content starts at pg=1

    # Header
    canvas.setFillColor(BRAND_DARK)
    canvas.rect(0, H - 13*mm, W, 13*mm, fill=1, stroke=0)
    canvas.setFont('Helvetica-Bold', 8)
    canvas.setFillColor(WHITE)
    canvas.drawString(MARGIN, H - 8.5*mm, 'TrintzPOS — User & System Manual')
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#90aad4'))
    canvas.drawRightString(W - MARGIN, H - 8.5*mm, 'by Trintz Data Labs')

    # Footer
    canvas.setFillColor(BRAND_DARK)
    canvas.rect(0, 0, W, 11*mm, fill=1, stroke=0)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#6090c0'))
    canvas.drawString(MARGIN, 3.5*mm, 'Confidential — Internal Use Only')
    canvas.setFont('Helvetica-Bold', 8)
    canvas.setFillColor(WHITE)
    canvas.drawCentredString(W/2, 3.5*mm, f'Page {pg}')
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#6090c0'))
    canvas.drawRightString(W - MARGIN, 3.5*mm, 'trintzpos.com')

    canvas.restoreState()


# ── Custom doc template ───────────────────────────────────────────────────────
def build_doc(filename):
    # Cover frame: full page, no margins (canvas draws on it directly)
    cover_frame  = Frame(0, 0, W, H, leftPadding=0, rightPadding=0,
                         topPadding=0, bottomPadding=0, id='cover')
    # Inner content frame
    inner_frame  = Frame(MARGIN, 11*mm + 4, W - 2*MARGIN, H - 13*mm - 11*mm - 8,
                         id='inner')

    cover_tpl  = PageTemplate(id='Cover',  frames=[cover_frame],  onPage=draw_cover)
    inner_tpl  = PageTemplate(id='Inner',  frames=[inner_frame],  onPage=draw_page)

    doc = BaseDocTemplate(
        filename,
        pagesize=A4,
        pageTemplates=[cover_tpl, inner_tpl],
        title='TrintzPOS — Complete User & System Manual',
        author='Trintz Data Labs',
        subject='TrintzPOS User Manual',
    )
    return doc


# ── Custom section header flowable ────────────────────────────────────────────
from reportlab.platypus import Flowable

class SectionHeader(Flowable):
    def __init__(self, text, content_width):
        Flowable.__init__(self)
        self.text  = text
        self.width  = content_width
        self.height = 22

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(BRAND_DARK)
        c.roundRect(0, 0, self.width, self.height, 5, fill=1, stroke=0)
        c.setFillColor(BRAND_ACCENT)
        c.roundRect(0, 0, 5, self.height, 3, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 10.5)
        c.setFillColor(WHITE)
        c.drawString(13, 6, self.text)
        c.restoreState()


class SubHeader(Flowable):
    def __init__(self, text, content_width):
        Flowable.__init__(self)
        self.text  = text
        self.width  = content_width
        self.height = 17

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(SECTION_BG)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        c.setFillColor(BRAND_ACCENT)
        c.rect(0, 0, 3, self.height, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(BRAND_DARK)
        c.drawString(10, 5, self.text)
        c.restoreState()


# ── Helpers ───────────────────────────────────────────────────────────────────
CW = W - 2*MARGIN   # content width

def esc(t):
    return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def body(t):
    return Paragraph(esc(t.strip()), BODY)

def bullet(t):
    return Paragraph(f'• {esc(t.strip())}', BULL)

def code(t):
    return Paragraph(esc(t.rstrip()), CODE)

def faq_q(t):
    return Paragraph(f'Q: {esc(t.strip())}', FAQQ)

def faq_a(t):
    return Paragraph(f'A: {esc(t.strip())}', FAQA)


# ── TOC page ──────────────────────────────────────────────────────────────────
TOC_SECTIONS = [
    ("1",  "System Overview"),
    ("2",  "Getting Started — Login and Registration"),
    ("3",  "Navigation and Sidebar"),
    ("4",  "User Roles and Permissions"),
    ("5",  "Sales — How to Create an Invoice"),
    ("6",  "Sales Returns — How to Process a Refund"),
    ("7",  "Purchase Orders — How to Record a Purchase"),
    ("8",  "Inventory Management"),
    ("9",  "Product Management"),
    ("10", "Supplier Management"),
    ("11", "Credit Customer Management"),
    ("12", "Reports"),
    ("13", "GST Reports — GSTR-1 and GSTR-3B"),
    ("14", "Admin Panel"),
    ("15", "User Management"),
    ("16", "Store Settings"),
    ("17", "AI Settings — Configuring AI Providers"),
    ("18", "AI Chat (Text-to-SQL)"),
    ("19", "Knowledge Base (RAG)"),
    ("20", "Backup and Restore"),
    ("21", "Tally Export"),
    ("22", "OCR to Excel"),
    ("23", "Data Upload (Bulk Import)"),
    ("24", "Login Activity Audit"),
    ("25", "Two-Factor Authentication (TOTP)"),
    ("26", "License Activation"),
    ("27", "Service Tools"),
    ("28", "All API Endpoints Reference"),
    ("29", "Database Schema Reference"),
    ("30", "Frequently Asked Questions"),
]

def build_toc():
    elements = [Spacer(1, 8)]
    elements.append(SectionHeader('TABLE OF CONTENTS', CW))
    elements.append(Spacer(1, 10))

    rows = []
    nst = sty('TN', fontSize=9, leading=14, fontName='Helvetica-Bold', textColor=BRAND_MID)
    tst = sty('TT', fontSize=9, leading=14, fontName='Helvetica', textColor=TEXT_DARK)
    for num, title in TOC_SECTIONS:
        rows.append([
            Paragraph(num, nst),
            Paragraph(esc(title), tst),
        ])

    t = Table(rows, colWidths=[14*mm, CW - 14*mm])
    t.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [WHITE, SECTION_BG]),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 7),
        ('RIGHTPADDING',  (0,0), (-1,-1), 7),
        ('LINEBELOW',     (0,0), (-1,-1), 0.3, BORDER_CLR),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t)
    elements.append(PageBreak())
    return elements


# ── Parse the .txt manual ─────────────────────────────────────────────────────
SECTION_NUM_RE = re.compile(r'^(\d+)\.\s+[A-Z]')
SUBHEAD_RE     = re.compile(r'^([A-Z][A-Z\s\(\)\-\/\:\.\+]{4,})$')
BULLET_RE      = re.compile(r'^\s{0,4}[-*]\s+(.+)$')
NUMBERED_RE    = re.compile(r'^(\d+)\.\s+(.+)$')
TABLE_SEP_RE   = re.compile(r'^\|[-|: ]+\|$')
TABLE_ROW_RE   = re.compile(r'^\|.+\|$')
FAQ_Q_RE       = re.compile(r'^Q:\s+(.+)$')
FAQ_A_RE       = re.compile(r'^A:\s+(.+)$')
HR_RE          = re.compile(r'^-{5,}$')
EQ_RE          = re.compile(r'^={5,}$')

def flush_table(rows, elements):
    if not rows:
        return
    data = []
    csty = ParagraphStyle('tc', fontSize=7.5, leading=10)
    for r in rows:
        cells = [Paragraph(esc(c.strip()), csty) for c in r.strip('|').split('|')]
        data.append(cells)
    if not data:
        return
    ncols = max(len(r) for r in data)
    cw    = CW / ncols
    t = Table(data, colWidths=[cw]*ncols, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),   BRAND_DARK),
        ('TEXTCOLOR',     (0,0), (-1,0),   WHITE),
        ('FONTNAME',      (0,0), (-1,0),   'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,0),   8),
        ('ROWBACKGROUNDS',(0,1), (-1,-1),  [WHITE, SECTION_BG]),
        ('GRID',          (0,0), (-1,-1),  0.4, BORDER_CLR),
        ('VALIGN',        (0,0), (-1,-1),  'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1),  3),
        ('BOTTOMPADDING', (0,0), (-1,-1),  3),
        ('LEFTPADDING',   (0,0), (-1,-1),  4),
        ('RIGHTPADDING',  (0,0), (-1,-1),  4),
    ]))
    elements.append(Spacer(1, 3))
    elements.append(t)
    elements.append(Spacer(1, 5))


def parse_manual(filepath):
    with open(filepath, encoding='utf-8') as f:
        lines = f.readlines()

    elements = []
    pending_table = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip('\n')
        stripped = line.strip()

        # flush pending table if we leave table context
        if pending_table and not TABLE_ROW_RE.match(stripped) and not TABLE_SEP_RE.match(stripped):
            flush_table(pending_table, elements)
            pending_table = []

        # Skip separator lines and initial title
        if EQ_RE.match(stripped) or (stripped.startswith('TRINTZPOS — COMPLETE USER') and i < 10):
            i += 1
            continue

        # Empty line
        if not stripped:
            elements.append(Spacer(1, 3))
            i += 1
            continue

        # HR -----
        if HR_RE.match(stripped):
            elements.append(Spacer(1, 2))
            elements.append(HRFlowable(width='100%', thickness=0.5, color=HR_CLR))
            elements.append(Spacer(1, 2))
            i += 1
            continue

        # Table separator
        if TABLE_SEP_RE.match(stripped):
            i += 1
            continue

        # Table row
        if TABLE_ROW_RE.match(stripped):
            pending_table.append(stripped)
            i += 1
            continue

        # FAQ
        m = FAQ_Q_RE.match(stripped)
        if m:
            elements.append(Spacer(1, 3))
            elements.append(faq_q(m.group(1)))
            i += 1
            continue
        m = FAQ_A_RE.match(stripped)
        if m:
            elements.append(faq_a(m.group(1)))
            i += 1
            continue

        # Main section "1. SYSTEM OVERVIEW"
        if SECTION_NUM_RE.match(stripped) and len(stripped.split()) <= 15:
            elements.append(Spacer(1, 8))
            elements.append(SectionHeader(stripped, CW))
            elements.append(Spacer(1, 5))
            i += 1
            continue

        # Sub-heading: ALL CAPS, 5-60 chars, few words, no trailing colon
        if (SUBHEAD_RE.match(stripped)
                and 5 <= len(stripped) <= 60
                and len(stripped.split()) <= 10
                and not stripped.endswith(':')
                and not stripped[0].isdigit()):
            elements.append(Spacer(1, 5))
            elements.append(SubHeader(stripped, CW))
            elements.append(Spacer(1, 4))
            i += 1
            continue

        # Bullet
        m = BULLET_RE.match(line)
        if m:
            elements.append(bullet(m.group(1)))
            i += 1
            continue

        # Numbered step (indented or not a top-level section)
        m = NUMBERED_RE.match(line)
        if m and not SECTION_NUM_RE.match(stripped):
            elements.append(bullet(f'{m.group(1)}. {m.group(2)}'))
            i += 1
            continue

        # Indented code/monospace
        if (line.startswith('  ') or line.startswith('\t')) and stripped:
            elements.append(code(stripped))
            i += 1
            continue

        # Body
        if stripped:
            elements.append(body(stripped))
        i += 1

    if pending_table:
        flush_table(pending_table, elements)

    return elements


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    base = os.path.dirname(os.path.abspath(__file__))
    src  = os.path.join(base, 'trintzpos_manual.txt')
    dst  = os.path.join(base, 'trintzpos_manual.pdf')

    print(f'Source : {src}')
    print(f'Output : {dst}')
    print('Building PDF ...')

    doc   = build_doc(dst)
    story = []

    # Page 1: cover (blank flowable — canvas draws it)
    story.append(Spacer(1, H))          # fills the cover page frame
    story.append(NextPageTemplate('Inner'))
    story.append(PageBreak())

    # Page 2+: TOC
    story.extend(build_toc())

    # Content
    story.extend(parse_manual(src))

    doc.build(story)

    size_kb = os.path.getsize(dst) / 1024
    print(f'Done!  {size_kb:.0f} KB  ->  {dst}')


if __name__ == '__main__':
    main()
