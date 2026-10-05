import os
import re

from fpdf import FPDF

BASE = r"C:\Users\nyong\Downloads\Jobs"
FONT_DIR = r"C:\Windows\Fonts"
SRC = os.path.join(BASE, "cv_text")
OUT = os.path.join(BASE, "cv_pdfs")
os.makedirs(OUT, exist_ok=True)

FILES = [
    ("Hope_John_Sunday_CV_ATS.txt", "Hope_John_Sunday_CV_ATS.pdf", "Master CV"),
    ("CV_IT_Support_ATS.txt", "Hope_John_Sunday_CV_IT_Support.pdf", "IT Support CV"),
    ("CV_Cloud_AWS_ATS.txt", "Hope_John_Sunday_CV_Cloud_AWS.pdf", "Cloud & AWS CV"),
    ("CV_Developer_ATS.txt", "Hope_John_Sunday_CV_Developer.pdf", "Developer CV"),
]

NAVY = (20, 43, 80)
DARK = (33, 33, 33)
GRAY = (90, 90, 90)


class CVPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Arial", "", os.path.join(FONT_DIR, "arial.ttf"))
        self.add_font("Arial", "B", os.path.join(FONT_DIR, "arialbd.ttf"))
        self.add_font("Arial", "I", os.path.join(FONT_DIR, "ariali.ttf"))
        self.add_font("Arial", "BI", os.path.join(FONT_DIR, "arialbi.ttf"))

    def header(self):
        pass

    def footer(self):
        pass


def section_header(pdf, title):
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 6, title, ln=True)
    pdf.set_line_width(0.5)
    pdf.set_draw_color(*NAVY)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def add_text_block(pdf, text, indent=6, body_size=10.5):
    pdf.set_font("Arial", "", body_size)
    pdf.set_text_color(*DARK)
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            pdf.ln(1.5)
            continue
        if line.startswith("-") or re.match(r"^\d+\.", line):
            bullet = "\u2022" if line.startswith("-") else ""
            content = line[1:].strip() if line.startswith("-") else line
            pdf.set_x(pdf.l_margin + indent)
            if bullet:
                pdf.cell(4, 5, bullet)
            pdf.multi_cell(0, 5, content, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_x(pdf.l_margin + indent)
            pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def add_label_block(pdf, text, label_size=10.5, body_size=10.5, indent=0):
    pdf.set_font("Arial", "B", label_size)
    pdf.set_text_color(*DARK)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            pdf.ln(1.5)
            continue
        if i == 0:
            pdf.set_x(pdf.l_margin + indent)
            pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Arial", "", body_size)
            pdf.set_x(pdf.l_margin + indent)
            pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def parse_block(text):
    blocks = []
    current = None
    lines = text.split("\n")
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        up = stripped.upper()
        is_header = (
            up.startswith(("PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "PROFESSIONAL CERTIFICATIONS",
                           "WORK EXPERIENCE", "PROJECTS", "EDUCATION", "CORE COMPETENCIES",
                           "LANGUAGES", "AVAILABILITY", "PRACTICAL EXPERIENCE"))
        )
        if is_header:
            if current:
                blocks.append(current)
            current = {"header": stripped, "body": []}
        else:
            if current:
                current["body"].append(line)
            else:
                blocks.append({"header": None, "body": [line]})
    if current:
        blocks.append(current)
    return blocks


def render(cv_txt_name, pdf_name, title):
    src = os.path.join(SRC, cv_txt_name)
    with open(src, encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    name = lines[0].strip()
    contact_parts = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            break
        contact_parts.append(line)

    pdf = CVPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()

    name = name.title()
    pdf.set_font("Arial", "B", 21)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, name, ln=True, align="C")
    pdf.ln(1)

    pdf.set_font("Arial", "", 10)
    pdf.set_text_color(*GRAY)
    for cp in contact_parts:
        pdf.cell(0, 4.6, cp, ln=True, align="C")
    pdf.ln(3)

    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.7)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)

    blocks = parse_block("\n".join(lines[2:]))

    label_cues = ("|", " - ", " \u2013 ", " \u2014 ")
    for block in blocks:
        if block["header"]:
            section_header(pdf, block["header"])
            pdf.set_font("Arial", "", 10.5)
            pdf.set_text_color(*DARK)
            label = ""
            for raw in block["body"]:
                line = raw.strip()
                if not line:
                    continue
                looks_label = False
                for cue in ["|", " - ", " \u2013 ", " \u2014 "]:
                    if cue in line:
                        looks_label = True
                        break
                if looks_label and len(line) < 140:
                    pdf.set_font("Arial", "B", 10.5)
                    pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Arial", "", 10.5)
                    continue
                if line.startswith("-") or re.match(r"^\d+\.", line):
                    bullet = "\u2022"
                    content = line[1:].strip() if line.startswith("-") else line
                    pdf.set_x(pdf.l_margin + 4)
                    pdf.cell(4, 5, bullet)
                    pdf.multi_cell(0, 5, content, new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.set_x(pdf.l_margin + 4)
                    pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        else:
            pdf.set_font("Arial", "", 10.5)
            pdf.set_text_color(*DARK)
            for raw in block["body"]:
                line = raw.strip()
                if line:
                    pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    out_path = os.path.join(OUT, pdf_name)
    pdf.output(out_path)
    print(f"[OK] {title} -> {out_path}")
    return out_path


for cv_txt, pdf_name, title in FILES:
    try:
        render(cv_txt, pdf_name, title)
    except Exception as e:
        print(f"[FAIL] {title}: {e}")
