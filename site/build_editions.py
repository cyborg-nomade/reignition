#!/usr/bin/env python3
"""Build the downloadable Reignition PDF and EPUB editions.

The four canonical tome PDFs are inputs and are never rewritten. The complete
PDF is assembled from newly typeset front matter plus those exact files. EPUBs
are generated from the semantic HTML/Markdown sources so they remain reflowable.
"""

from __future__ import annotations

import html
import posixpath
import re
import textwrap
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import markdown
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from generate import DOCS_ROOT, TOMES, Page, assign_paths, parse_tome, relative_link, slugify


SITE_ROOT = Path(__file__).resolve().parent
ROOT = SITE_ROOT.parent
OUTPUT_ROOT = ROOT / "pdf-epub"
TEMP_ROOT = ROOT / "tmp" / "pdfs"
INTRODUCTION = DOCS_ROOT / "editors-introduction.md"
SITE_URL = "https://cyborg-nomade.github.io/reignition/"
PAGE_SIZE = (7 * inch, 9.25 * inch)

INTRO_PDF = OUTPUT_ROOT / "reignition-introduction.pdf"
COMPLETE_PDF = OUTPUT_ROOT / "reignition-complete.pdf"

TOME_PDFS = tuple(OUTPUT_ROOT / f"tome{number}.pdf" for number in range(1, 5))

PDF_ACCENT = colors.HexColor("#4a126e")
PDF_INK = colors.HexColor("#171613")
PDF_PAPER = colors.HexColor("#f1eee5")
PDF_MUTED = colors.HexColor("#6d695f")
PDF_ORANGE = colors.HexColor("#b2462d")


@dataclass(frozen=True)
class Edition:
    title: str
    subtitle: str
    filename: str
    creator: str
    introduction: bool = False
    tome_numbers: tuple[int, ...] = ()


class OutlineHeading(Paragraph):
    def __init__(self, text: str, style: ParagraphStyle, anchor: str, level: int) -> None:
        super().__init__(f'<a name="{html.escape(anchor, quote=True)}"/>{text}', style)
        self.outline_title = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        self.outline_anchor = anchor
        self.outline_level = level


class PublicationDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable: object) -> None:
        if isinstance(flowable, OutlineHeading):
            self.canv.bookmarkPage(flowable.outline_anchor)
            self.canv.addOutlineEntry(
                flowable.outline_title,
                flowable.outline_anchor,
                level=flowable.outline_level,
                closed=False,
            )


def strip_frontmatter(markdown_text: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", markdown_text, count=1, flags=re.S)


def load_introduction_html() -> str:
    source = strip_frontmatter(INTRODUCTION.read_text(encoding="utf-8"))
    return markdown.markdown(
        source,
        extensions=["attr_list", "extra", "md_in_html", "sane_lists"],
        output_format="html5",
    )


def publication_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PublicationTitle",
            parent=sample["Title"],
            fontName="Helvetica",
            fontSize=32,
            leading=34,
            textColor=PDF_INK,
            alignment=TA_LEFT,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "PublicationSubtitle",
            parent=sample["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=19,
            textColor=PDF_INK,
            alignment=TA_LEFT,
            spaceAfter=20,
        ),
        "byline": ParagraphStyle(
            "PublicationByline",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=PDF_MUTED,
            alignment=TA_LEFT,
            uppercase=True,
        ),
        "kicker": ParagraphStyle(
            "PublicationKicker",
            parent=sample["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=11,
            textColor=PDF_MUTED,
            spaceBefore=2,
            spaceAfter=14,
            uppercase=True,
        ),
        "h1": ParagraphStyle(
            "PublicationH1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=28,
            textColor=PDF_INK,
            spaceBefore=4,
            spaceAfter=18,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "PublicationH2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=19,
            textColor=PDF_INK,
            spaceBefore=21,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "PublicationBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=10.6,
            leading=15.4,
            textColor=PDF_INK,
            alignment=TA_JUSTIFY,
            firstLineIndent=13,
            spaceAfter=3,
            allowWidows=False,
            allowOrphans=False,
        ),
        "body-first": ParagraphStyle(
            "PublicationBodyFirst",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=10.6,
            leading=15.4,
            textColor=PDF_INK,
            alignment=TA_JUSTIFY,
            firstLineIndent=0,
            spaceAfter=3,
            allowWidows=False,
            allowOrphans=False,
        ),
        "toc-title": ParagraphStyle(
            "PublicationTocTitle",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=25,
            textColor=PDF_INK,
            spaceAfter=18,
        ),
        "toc": ParagraphStyle(
            "PublicationToc",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=PDF_INK,
            leftIndent=0,
            spaceAfter=3,
        ),
        "toc-major": ParagraphStyle(
            "PublicationTocMajor",
            parent=sample["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=16,
            textColor=PDF_INK,
            spaceBefore=5,
            spaceAfter=3,
        ),
        "note": ParagraphStyle(
            "PublicationNote",
            parent=sample["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=13,
            textColor=PDF_MUTED,
            alignment=TA_LEFT,
            spaceBefore=15,
        ),
    }


def to_public_url(value: str) -> str:
    if value.startswith(("https://", "http://", "mailto:", "#")):
        return value
    if value.endswith(".md") or ".md#" in value:
        path, separator, fragment = value.partition("#")
        clean = path.removesuffix("index.md").removesuffix(".md")
        clean = clean.rstrip("/") + "/"
        return f"{SITE_URL}{clean}{separator}{fragment}" if separator else f"{SITE_URL}{clean}"
    return value


def reportlab_inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return html.escape(str(node))
    inner = "".join(reportlab_inline(child) for child in node.children)
    if node.name in {"em", "i"}:
        return f"<i>{inner}</i>"
    if node.name in {"strong", "b"}:
        return f"<b>{inner}</b>"
    if node.name == "code":
        return f'<font name="Courier">{inner}</font>'
    if node.name == "a":
        href = html.escape(to_public_url(node.get("href", "")), quote=True)
        return f'<link href="{href}" color="#8d3421">{inner}</link>'
    if node.name == "br":
        return "<br/>"
    return inner


def introduction_flowables(styles: dict[str, ParagraphStyle]) -> tuple[list[object], list[tuple[str, str]]]:
    soup = BeautifulSoup(load_introduction_html(), "html.parser")
    story: list[object] = []
    toc: list[tuple[str, str]] = []
    after_heading = True
    seen_anchors: set[str] = set()

    for element in soup.contents:
        if isinstance(element, NavigableString) or not isinstance(element, Tag):
            continue
        if element.name in {"h1", "h2"}:
            title = element.get_text(" ", strip=True)
            base = slugify(title, "section")
            anchor = base
            suffix = 2
            while anchor in seen_anchors:
                anchor = f"{base}-{suffix}"
                suffix += 1
            seen_anchors.add(anchor)
            level = 0 if element.name == "h1" else 1
            style = styles["h1"] if element.name == "h1" else styles["h2"]
            heading = OutlineHeading(html.escape(title), style, anchor, level)
            if element.name == "h2":
                rule = Paragraph('<font color="#b2462d">―</font>', styles["toc-major"])
                story.append(KeepTogether([rule, heading]))
                toc.append((title, anchor))
            else:
                story.append(heading)
            after_heading = True
        elif element.name == "p":
            inline = "".join(reportlab_inline(child) for child in element.children)
            if not inline.strip():
                continue
            if "tome-kicker" in element.get("class", []):
                story.append(Paragraph(inline.upper(), styles["kicker"]))
            else:
                style = styles["body-first"] if after_heading else styles["body"]
                story.append(Paragraph(inline, style))
                after_heading = False
        elif element.name in {"ul", "ol"}:
            for item in element.find_all("li", recursive=False):
                inline = "".join(reportlab_inline(child) for child in item.children)
                story.append(Paragraph(f"•&nbsp;&nbsp;{inline}", styles["body-first"]))
            after_heading = False

    return story, toc


def draw_cover(canvas: object, doc: PublicationDocTemplate) -> None:
    width, height = PAGE_SIZE
    canvas.saveState()
    canvas.setFillColor(PDF_PAPER)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#e7e1d4"))
    canvas.rect(width * 0.57, 0, width * 0.08, height, fill=1, stroke=0)
    canvas.setFillColor(PDF_ORANGE)
    canvas.rect(width * 0.612, 0, 3, height, fill=1, stroke=0)

    canvas.setFillColor(PDF_INK)
    canvas.setFont("Helvetica", 35)
    canvas.drawString(24, height - 57, "Reignition")
    text = canvas.beginText(27, height - 74)
    text.setFont("Helvetica", 7.8)
    text.setCharSpace(1.55)
    text.textLine("NICK LAND'S WRITINGS (2011-)")
    canvas.drawText(text)

    canvas.setFillColor(PDF_ACCENT)
    canvas.rect(width - 58, height - 58, 34, 34, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Bold", 25)
    canvas.drawCentredString(width - 41, height - 50, "E")

    canvas.setFillColor(PDF_INK)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(24, 91, doc.cover_label)
    canvas.setFont("Helvetica", 9.5)
    lines = textwrap.wrap(doc.cover_subtitle, width=58)
    y = 72
    for line in lines:
        canvas.drawString(24, y, line)
        y -= 13
    canvas.restoreState()


def draw_running_page(canvas: object, doc: PublicationDocTemplate) -> None:
    physical_page = canvas.getPageNumber()
    if physical_page <= 2:
        return
    width, height = PAGE_SIZE
    display_page = physical_page - 2
    canvas.saveState()
    canvas.setFillColor(PDF_MUTED)
    canvas.setFont("Helvetica", 7.5)
    if physical_page % 2:
        canvas.drawString(16 * mm, height - 15 * mm, "REIGNITION")
        right = "EDITOR'S INTRODUCTION"
        canvas.drawRightString(width - 16 * mm, height - 15 * mm, right)
        canvas.drawRightString(width - 16 * mm, 12 * mm, str(display_page))
    else:
        canvas.drawString(16 * mm, height - 15 * mm, "EDITOR'S INTRODUCTION")
        canvas.drawRightString(width - 16 * mm, height - 15 * mm, "REIGNITION")
        canvas.drawString(16 * mm, 12 * mm, str(display_page))
    canvas.setStrokeColor(colors.HexColor("#d3cec2"))
    canvas.setLineWidth(0.35)
    canvas.line(16 * mm, height - 18 * mm, width - 16 * mm, height - 18 * mm)
    canvas.restoreState()


def title_page(styles: dict[str, ParagraphStyle], subtitle: str) -> list[object]:
    return [
        Spacer(1, 98),
        Paragraph("Reignition", styles["title"]),
        Paragraph("Nick Land’s Writings (2011–)", styles["byline"]),
        Spacer(1, 205),
        Paragraph(subtitle, styles["subtitle"]),
        Spacer(1, 25),
        Paragraph("Edited by Uriel Fiori", styles["byline"]),
        PageBreak(),
    ]


def intro_toc(styles: dict[str, ParagraphStyle], headings: list[tuple[str, str]], complete: bool) -> list[object]:
    items: list[object] = [Paragraph("Contents", styles["toc-title"])]
    items.append(Paragraph('<link href="#editors-introduction" color="#171613">Editor’s Introduction</link>', styles["toc-major"]))
    for title, anchor in headings:
        items.append(Paragraph(f'<link href="#{html.escape(anchor, quote=True)}" color="#171613">{html.escape(title)}</link>', styles["toc"]))
    if complete:
        items.extend([Spacer(1, 10), Paragraph("The Four Tomes", styles["toc-major"])])
        for number, roman, title, subtitle in TOMES:
            items.append(Paragraph(f"{html.escape(roman)} · {html.escape(title)} — {html.escape(subtitle)}", styles["toc"]))
        items.append(
            Paragraph(
                "The four original Prince editions follow the introduction unchanged and retain their own pagination.",
                styles["note"],
            )
        )
    items.append(PageBreak())
    return items


def build_introduction_pdf(path: Path, *, complete_frontmatter: bool = False) -> None:
    styles = publication_styles()
    intro_story, headings = introduction_flowables(styles)
    subtitle = "Complete Edition" if complete_frontmatter else "Editor’s Introduction"
    cover_label = "COMPLETE EDITION" if complete_frontmatter else "EDITOR’S INTRODUCTION"
    cover_subtitle = (
        "Editor's Introduction and Four Tomes"
        if complete_frontmatter
        else "A Map of the River · Uriel Fiori"
    )
    doc = PublicationDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=27 * mm,
        bottomMargin=22 * mm,
        title=f"Reignition — {subtitle}",
        author="Uriel Fiori" if not complete_frontmatter else "Nick Land; edited by Uriel Fiori",
        subject="Editor’s introduction to Reignition",
    )
    doc.cover_label = cover_label
    doc.cover_subtitle = cover_subtitle
    story: list[object] = [Spacer(1, 475), PageBreak()]
    story.extend(title_page(styles, subtitle))
    story.extend(intro_toc(styles, headings, complete_frontmatter))
    story.extend(intro_story)
    doc.build(story, onFirstPage=draw_cover, onLaterPages=draw_running_page)


def merge_complete_pdf(frontmatter: Path, output: Path) -> None:
    writer = PdfWriter()
    writer.append(str(frontmatter), import_outline=True)
    for (_, roman, title, _), source in zip(TOMES, TOME_PDFS, strict=True):
        writer.append(str(source), outline_item=f"{roman} · {title}", import_outline=True)
    writer.add_metadata(
        {
            "/Title": "Reignition — Complete Edition",
            "/Author": "Nick Land; edited by Uriel Fiori",
            "/Subject": "Editor’s Introduction and Four Tomes",
            "/Creator": "Reignition publication builder",
        }
    )
    writer.page_mode = "/UseOutlines"
    with output.open("wb") as stream:
        writer.write(stream)


def load_tomes() -> dict[int, Page]:
    tomes: dict[int, Page] = {}
    for metadata in TOMES:
        number = metadata[0]
        tome = parse_tome(*metadata)
        assign_paths(tome, DOCS_ROOT / f"tome-{number}")
        tomes[number] = tome
    return tomes


def walk_pages(node: Page, parents: tuple[Page, ...] = ()) -> list[tuple[Page, tuple[Page, ...]]]:
    pages = [(node, parents)]
    for child in node.children:
        pages.extend(walk_pages(child, parents + (node,)))
    return pages


def all_page_maps(tomes: dict[int, Page], selected: tuple[int, ...]) -> tuple[dict[str, str], dict[int, str]]:
    source_to_epub: dict[str, str] = {}
    object_to_epub: dict[int, str] = {}
    for number in selected:
        for page, _ in walk_pages(tomes[number]):
            assert page.path is not None
            source = page.path.relative_to(DOCS_ROOT).as_posix()
            if page.kind == "tome":
                epub_path = f"text/tome-{number}/index.xhtml"
            elif page.kind == "article":
                epub_path = "text/" + page.path.relative_to(DOCS_ROOT).with_suffix(".xhtml").as_posix()
            else:
                epub_path = "text/" + page.path.relative_to(DOCS_ROOT).with_suffix(".xhtml").as_posix()
            source_to_epub[source] = epub_path
            object_to_epub[id(page)] = epub_path
    return source_to_epub, object_to_epub


def epub_link(value: str, current: str, source_to_epub: dict[str, str]) -> str:
    if not value or value.startswith(("https://", "http://", "mailto:", "data:", "#")):
        return value
    if value.startswith("//"):
        return "https:" + value
    path, separator, fragment = value.partition("#")
    normalized = str((DOCS_ROOT / path).resolve().relative_to(DOCS_ROOT.resolve())) if path else ""
    target = source_to_epub.get(normalized)
    if target:
        relative = relative_link(Path(current), Path(target))
        return f"{relative}#{fragment}" if separator else relative
    if path.endswith(".md"):
        clean = path.removesuffix("index.md").removesuffix(".md").rstrip("/") + "/"
        external = f"{SITE_URL}{clean}"
        return f"{external}#{fragment}" if separator else external
    return value


def clean_xhtml_fragment(fragment: str, current: str, source_to_epub: dict[str, str]) -> tuple[str, bool]:
    soup = BeautifulSoup(fragment, "html.parser")
    remote_resources = False
    for element in soup.find_all(["script", "iframe", "object", "embed"]):
        element.decompose()
    for element in soup.find_all(True):
        element.attrs.pop("style", None)
        element.attrs.pop("onclick", None)
        if element.name == "a" and element.get("href"):
            element["href"] = epub_link(element["href"], current, source_to_epub)
        if element.name == "img" and element.get("src"):
            source = element["src"]
            if source.startswith("//"):
                source = "https:" + source
                element["src"] = source
            if source.startswith(("http://", "https://")):
                remote_resources = True
            element.attrs.pop("srcset", None)
            element.attrs.pop("loading", None)
            if not element.get("alt"):
                element["alt"] = ""
    return soup.decode(formatter="minimal"), remote_resources


def xhtml_document(title: str, body: str, stylesheet_path: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">\n'
        "<head>\n"
        f"  <title>{html.escape(title)}</title>\n"
        f'  <link rel="stylesheet" type="text/css" href="{html.escape(stylesheet_path, quote=True)}"/>\n'
        "</head>\n"
        f"<body>\n{body}\n</body>\n"
        "</html>\n"
    )


def page_xhtml(
    page: Page,
    parents: tuple[Page, ...],
    epub_path: str,
    source_to_epub: dict[str, str],
    object_to_epub: dict[int, str],
) -> tuple[str, bool]:
    stylesheet = relative_link(Path(epub_path), Path("styles/ebook.css"))
    breadcrumb = " / ".join(parent.title for parent in parents if parent.kind != "tome")
    if page.kind == "article":
        article_body = markdown.markdown(
            page.body,
            extensions=["attr_list", "extra", "footnotes", "sane_lists"],
            output_format="html5",
        )
        article_body, remote = clean_xhtml_fragment(article_body, epub_path, source_to_epub)
        meta = " · ".join(part for part in (breadcrumb, page.date) if part)
        source = (
            f'<p class="source"><a href="{html.escape(page.source_url, quote=True)}">Read the original post</a></p>'
            if page.source_url
            else ""
        )
        body = (
            '<section class="article">'
            f"<h1>{html.escape(page.title)}</h1>"
            f'<p class="meta">{html.escape(meta)}</p>'
            f"{source}{article_body}</section>"
        )
        return xhtml_document(page.title, body, stylesheet), remote

    child_items: list[str] = []
    for child in page.children:
        target = relative_link(Path(epub_path), Path(object_to_epub[id(child)]))
        detail = f" — {child.date}" if child.kind == "article" and child.date else ""
        child_items.append(
            f'<li><a href="{html.escape(target, quote=True)}">{html.escape(child.title)}</a>{html.escape(detail)}</li>'
        )
    subtitle = f'<p class="subtitle">{html.escape(page.source_id)}</p>' if page.kind == "tome" else ""
    label = "Contents" if page.kind == "tome" else f"In this {page.kind}"
    body = (
        '<section class="overview">'
        f"<h1>{html.escape(page.title)}</h1>{subtitle}"
        f"<h2>{html.escape(label)}</h2><ol>{''.join(child_items)}</ol>"
        "</section>"
    )
    return xhtml_document(page.title, body, stylesheet), False


def introduction_xhtml(
    epub_path: str,
    source_to_epub: dict[str, str],
) -> tuple[str, bool]:
    stylesheet = relative_link(Path(epub_path), Path("styles/ebook.css"))
    fragment, remote = clean_xhtml_fragment(load_introduction_html(), epub_path, source_to_epub)
    return xhtml_document("Editor’s Introduction", f'<section class="introduction">{fragment}</section>', stylesheet), remote


def find_cover_font(bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if bold else ["DejaVuSans.ttf", "Arial.ttf"]
    roots = (
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
    )
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.exists():
                return ImageFont.truetype(str(candidate), 76 if bold else 58)
    try:
        return ImageFont.truetype(names[0], 76 if bold else 58)
    except OSError:
        return ImageFont.load_default()


def generated_cover(title: str, subtitle: str) -> bytes:
    from io import BytesIO

    width, height = 1400, 1850
    image = Image.new("RGB", (width, height), "#f1eee5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((800, 0, 915, height), fill="#e7e1d4")
    draw.rectangle((858, 0, 866, height), fill="#b2462d")
    title_font = find_cover_font(bold=False)
    label_font = find_cover_font(bold=True)
    small_font = ImageFont.truetype(getattr(title_font, "path", "DejaVuSans.ttf"), 26) if hasattr(title_font, "path") else title_font
    draw.text((68, 68), "Reignition", fill="#171613", font=title_font)
    draw.text((74, 155), "NICK LAND'S WRITINGS (2011-)", fill="#171613", font=small_font)
    draw.rectangle((width - 170, 68, width - 68, 170), fill="#4a126e")
    draw.text((width - 137, 76), "E", fill="white", font=label_font)
    draw.text((68, height - 260), title.upper(), fill="#171613", font=small_font)
    y = height - 205
    for line in textwrap.wrap(subtitle, width=38):
        draw.text((68, y), line, fill="#171613", font=small_font)
        y += 38
    data = BytesIO()
    image.save(data, format="PNG", optimize=True)
    return data.getvalue()


EPUB_CSS = """
@charset "utf-8";
body {
  color: #171613;
  background: #fff;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.55;
  margin: 5%;
}
h1, h2, h3, h4, h5, h6, .meta, .source, .subtitle {
  font-family: Arial, Helvetica, sans-serif;
}
h1 { font-size: 2em; line-height: 1.05; margin: 1.8em 0 0.8em; }
h2 { border-top: 1px solid #c9c4b8; font-size: 1.35em; margin-top: 2.2em; padding-top: 0.8em; }
h3 { font-size: 1.15em; margin-top: 1.8em; }
p { margin: 0; text-align: justify; }
p + p { text-indent: 1.25em; }
.meta, .source, .subtitle { color: #6d695f; font-size: 0.78em; text-align: left; text-indent: 0; }
.source { margin: 0.7em 0 1.6em; }
.subtitle { font-size: 0.95em; margin-bottom: 2em; }
a { color: #8d3421; }
blockquote { border-left: 0.2em solid #b2462d; margin-left: 0; padding-left: 1em; }
img { height: auto; max-width: 100%; }
pre, code { font-family: monospace; white-space: pre-wrap; }
.cover { margin: 0; padding: 0; text-align: center; }
.cover img { height: 100%; max-height: 100vh; max-width: 100%; }
ol, ul { padding-left: 1.4em; }
li { margin: 0.25em 0; }
""".strip()


def nested_nav(
    node: Page,
    nav_path: str,
    object_to_epub: dict[int, str],
) -> str:
    target = relative_link(Path(nav_path), Path(object_to_epub[id(node)]))
    children = "".join(nested_nav(child, nav_path, object_to_epub) for child in node.children)
    nested = f"<ol>{children}</ol>" if children else ""
    return f'<li><a href="{html.escape(target, quote=True)}">{html.escape(node.title)}</a>{nested}</li>'


def nav_xhtml(
    edition: Edition,
    tomes: dict[int, Page],
    object_to_epub: dict[int, str],
) -> str:
    items: list[str] = []
    if edition.introduction:
        items.append('<li><a href="text/introduction.xhtml">Editor’s Introduction</a></li>')
    for number in edition.tome_numbers:
        items.append(nested_nav(tomes[number], "nav.xhtml", object_to_epub))
    body = (
        '<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc" id="toc">'
        f"<h1>{html.escape(edition.title)}</h1><ol>{''.join(items)}</ol></nav>"
    )
    return xhtml_document("Contents", body, "styles/ebook.css")


def ncx_document(edition: Edition, labels_and_targets: list[tuple[str, str]], uid: str) -> str:
    points = []
    for index, (label, target) in enumerate(labels_and_targets, start=1):
        points.append(
            f'<navPoint id="nav-{index}" playOrder="{index}"><navLabel><text>{html.escape(label)}</text></navLabel>'
            f'<content src="{html.escape(target, quote=True)}"/></navPoint>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{html.escape(uid, quote=True)}"/></head>'
        f"<docTitle><text>{html.escape(edition.title)}</text></docTitle>"
        f"<navMap>{''.join(points)}</navMap></ncx>"
    )


def manifest_item_xml(item_id: str, href: str, media: str, properties: str) -> str:
    properties_attribute = (
        f' properties="{html.escape(properties, quote=True)}"' if properties else ""
    )
    return (
        f'<item id="{html.escape(item_id, quote=True)}" '
        f'href="{html.escape(href, quote=True)}" '
        f'media-type="{html.escape(media, quote=True)}"{properties_attribute}/>'
    )


def build_epub(edition: Edition, tomes: dict[int, Page]) -> None:
    output = OUTPUT_ROOT / edition.filename
    source_to_epub, object_to_epub = all_page_maps(tomes, edition.tome_numbers)
    files: dict[str, bytes] = {}
    manifest: list[tuple[str, str, str, str]] = []
    spine: list[str] = []
    flat_nav: list[tuple[str, str]] = []

    if edition.tome_numbers and len(edition.tome_numbers) == 1 and not edition.introduction:
        number = edition.tome_numbers[0]
        cover_bytes = (ROOT / "html" / "tomes" / f"tome{number}-cover.png").read_bytes()
    else:
        cover_bytes = generated_cover(edition.title, edition.subtitle)
    files["images/cover.png"] = cover_bytes
    manifest.append(("cover-image", "images/cover.png", "image/png", "cover-image"))

    cover_body = '<section class="cover" epub:type="cover"><img src="images/cover.png" alt="Cover"/></section>'
    cover_doc = xhtml_document("Cover", cover_body, "styles/ebook.css").replace(
        '<html xmlns="http://www.w3.org/1999/xhtml"',
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"',
    )
    files["cover.xhtml"] = cover_doc.encode("utf-8")
    manifest.append(("cover", "cover.xhtml", "application/xhtml+xml", ""))
    spine.append("cover")

    if edition.introduction:
        path = "text/introduction.xhtml"
        content, remote = introduction_xhtml(path, source_to_epub)
        files[path] = content.encode("utf-8")
        manifest.append(("introduction", path, "application/xhtml+xml", "remote-resources" if remote else ""))
        spine.append("introduction")
        flat_nav.append(("Editor’s Introduction", path))

    item_counter = 0
    for number in edition.tome_numbers:
        for page, parents in walk_pages(tomes[number]):
            item_counter += 1
            item_id = f"page-{item_counter}"
            path = object_to_epub[id(page)]
            content, remote = page_xhtml(page, parents, path, source_to_epub, object_to_epub)
            files[path] = content.encode("utf-8")
            properties = "remote-resources" if remote else ""
            manifest.append((item_id, path, "application/xhtml+xml", properties))
            spine.append(item_id)
            flat_nav.append((page.title, path))

    files["styles/ebook.css"] = EPUB_CSS.encode("utf-8")
    manifest.append(("style", "styles/ebook.css", "text/css", ""))
    files["nav.xhtml"] = nav_xhtml(edition, tomes, object_to_epub).encode("utf-8")
    manifest.append(("nav", "nav.xhtml", "application/xhtml+xml", "nav"))

    uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, SITE_URL + edition.filename)}"
    files["toc.ncx"] = ncx_document(edition, flat_nav, uid).encode("utf-8")
    manifest.append(("ncx", "toc.ncx", "application/x-dtbncx+xml", ""))

    modified = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest_xml = "".join(manifest_item_xml(*item) for item in manifest)
    spine_xml = "".join(f'<itemref idref="{item_id}"/>' for item_id in spine)
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="pub-id">{html.escape(uid)}</dc:identifier>'
        f"<dc:title>{html.escape(edition.title)}</dc:title>"
        f"<dc:creator>{html.escape(edition.creator)}</dc:creator>"
        '<dc:contributor id="editor">Uriel Fiori</dc:contributor>'
        '<meta refines="#editor" property="role" scheme="marc:relators">edt</meta>'
        '<dc:language>en</dc:language>'
        f'<meta property="dcterms:modified">{modified}</meta>'
        "</metadata>"
        f"<manifest>{manifest_xml}</manifest>"
        f'<spine toc="ncx">{spine_xml}</spine>'
        "</package>"
    )
    files["content.opf"] = opf.encode("utf-8")

    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )

    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        for path, data in files.items():
            archive.writestr(f"OEBPS/{path}", data, compress_type=zipfile.ZIP_DEFLATED)


def validate_epub(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names[0] != "mimetype" or archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            raise ValueError(f"{path.name}: mimetype must be the first uncompressed entry")
        if archive.read("mimetype") != b"application/epub+zip":
            raise ValueError(f"{path.name}: invalid mimetype")
        for name in names:
            if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
                ElementTree.fromstring(archive.read(name))

        package = ElementTree.fromstring(archive.read("OEBPS/content.opf"))
        namespace = {"opf": "http://www.idpf.org/2007/opf"}
        manifest = {
            item.attrib["id"]: item.attrib["href"]
            for item in package.findall("opf:manifest/opf:item", namespace)
        }
        for href in manifest.values():
            if f"OEBPS/{href}" not in names:
                raise ValueError(f"{path.name}: manifest target is missing: {href}")
        for itemref in package.findall("opf:spine/opf:itemref", namespace):
            if itemref.attrib["idref"] not in manifest:
                raise ValueError(f"{path.name}: unknown spine id {itemref.attrib['idref']}")

        for name in (entry for entry in names if entry.endswith(".xhtml")):
            document = ElementTree.fromstring(archive.read(name))
            for element in document.iter():
                for attribute in ("href", "src"):
                    value = element.attrib.get(attribute, "")
                    if not value or value.startswith(
                        ("https://", "http://", "mailto:", "data:", "#")
                    ):
                        continue
                    target_path = value.partition("#")[0].partition("?")[0]
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(name), target_path)
                    )
                    if target not in names:
                        raise ValueError(
                            f"{path.name}: {name} links to missing resource {value}"
                        )


def validate_pdfs(complete_frontmatter: Path) -> None:
    intro = PdfReader(INTRO_PDF)
    frontmatter = PdfReader(complete_frontmatter)
    complete = PdfReader(COMPLETE_PDF)
    tome_pages = sum(len(PdfReader(path).pages) for path in TOME_PDFS)
    if len(frontmatter.pages) != len(intro.pages):
        raise ValueError("Standalone and complete-edition front matter have different lengths")
    if len(complete.pages) != len(frontmatter.pages) + tome_pages:
        raise ValueError("Complete PDF page count does not equal introduction plus four tomes")
    expected_size = tuple(round(float(value), 2) for value in PAGE_SIZE)
    for label, reader in (("introduction", intro), ("complete", complete)):
        for index in (0, len(reader.pages) // 2, len(reader.pages) - 1):
            box = reader.pages[index].mediabox
            actual = (round(float(box.width), 2), round(float(box.height), 2))
            if actual != expected_size:
                raise ValueError(f"{label} PDF has an unexpected page size at page {index + 1}: {actual}")
    intro_text = "\n".join((intro.pages[index].extract_text() or "") for index in (2, len(intro.pages) - 1))
    if "Editor’s Introduction" not in intro_text or "reading begins again" not in intro_text:
        raise ValueError("Introduction PDF text check failed")


def main() -> None:
    missing = [str(path) for path in (*TOME_PDFS, INTRODUCTION) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing publication sources: " + ", ".join(missing))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    build_introduction_pdf(INTRO_PDF)
    frontmatter = TEMP_ROOT / "reignition-complete-frontmatter.pdf"
    build_introduction_pdf(frontmatter, complete_frontmatter=True)
    merge_complete_pdf(frontmatter, COMPLETE_PDF)

    tomes = load_tomes()
    editions = [
        Edition(
            title="Reignition — Editor’s Introduction",
            subtitle="A Map of the River · Uriel Fiori",
            filename="reignition-introduction.epub",
            creator="Uriel Fiori",
            introduction=True,
        ),
        *(
            Edition(
                title=f"Reignition — {roman}: {title}",
                subtitle=subtitle,
                filename=f"tome{number}.epub",
                creator="Nick Land",
                tome_numbers=(number,),
            )
            for number, roman, title, subtitle in TOMES
        ),
        Edition(
            title="Reignition — Complete Edition",
            subtitle="Editor’s Introduction and Four Tomes",
            filename="reignition-complete.epub",
            creator="Nick Land",
            introduction=True,
            tome_numbers=(1, 2, 3, 4),
        ),
    ]
    for edition in editions:
        build_epub(edition, tomes)

    validate_pdfs(frontmatter)
    for edition in editions:
        validate_epub(OUTPUT_ROOT / edition.filename)

    frontmatter.unlink(missing_ok=True)
    try:
        TEMP_ROOT.rmdir()
        TEMP_ROOT.parent.rmdir()
    except OSError:
        pass

    print(f"Built {INTRO_PDF.name} and {COMPLETE_PDF.name}.")
    print("Built six validated EPUB editions.")


if __name__ == "__main__":
    main()
