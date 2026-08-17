#!/usr/bin/env python3
"""Generate the Reignition Markdown edition from the four canonical tomes."""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter


SITE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = SITE_ROOT.parent / "html" / "tomes"
DOCS_ROOT = SITE_ROOT / "docs"
GENERATED_ROOTS = tuple(DOCS_ROOT / f"tome-{number}" for number in range(1, 5))
STRUCTURAL_KINDS = {"block", "section", "chapter", "sequence"}

TOMES = (
    (1, "Tome I", "Urban Future", "Views from the Decopunk Delta"),
    (2, "Tome II", "The Dark Enlightenment", "Neoreactionaries Head for the Exit"),
    (3, "Tome III", "Xenosystems", "Involvements with Reality"),
    (4, "Tome IV", "Abstract Horror", "The Unknown, as The Unknown"),
)


@dataclass
class Page:
    title: str
    kind: str
    source_id: str = ""
    source_url: str = ""
    date: str = ""
    body: str = ""
    children: list[Page] = field(default_factory=list)
    path: Path | None = None


class ReignitionConverter(MarkdownConverter):
    """Keep named anchors so the one source article with footnotes still works."""

    def convert_a(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        anchor_name = el.get("name") or el.get("id")
        anchor = f'<a id="{anchor_name}"></a>' if anchor_name else ""
        return anchor + super().convert_a(el, text, parent_tags)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def slugify(value: str, fallback: str = "page") -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or fallback


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize_url(value: str) -> str:
    value = value.strip().strip("\u200e\u200f\ufeff")
    if value.startswith("http://"):
        return "https://" + value.removeprefix("http://")
    if re.match(r"^(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/|$)", value, re.I):
        return "https://" + value
    return value


def section_kind(section: Tag) -> str:
    classes = section.get("class", [])
    return next((kind for kind in STRUCTURAL_KINDS | {"post"} if kind in classes), "")


def section_title(section: Tag, soup: BeautifulSoup) -> str:
    kind = section_kind(section)
    title = section.find(class_=f"{kind}-title") if kind else None
    if not title:
        title = section.find(re.compile(r"^h[1-6]$"), recursive=False)
    if title:
        return clean_text(title.get_text(" ", strip=True))

    source_id = section.get("id", "")
    if source_id:
        toc_link = soup.select_one(f'a[href="#{source_id}"]')
        if toc_link:
            return clean_text(toc_link.get_text(" ", strip=True))
    return source_id or "Untitled section"


def post_to_page(section: Tag) -> Page:
    title_element = section.find(class_="post-title")
    if not title_element:
        title_element = section.find(re.compile(r"^h[1-6]$"))
    title = clean_text(title_element.get_text(" ", strip=True)) if title_element else "Untitled"

    source_link = title_element.find_parent("a", href=True) if title_element else None
    source_url = source_link.get("href", "") if source_link else ""
    date_element = section.find(class_="post-date")
    date = clean_text(date_element.get_text(" ", strip=True)) if date_element else ""

    fragment = BeautifulSoup(str(section), "html.parser")
    fragment_title = fragment.find(class_="post-title")
    if fragment_title:
        parent_link = fragment_title.find_parent("a")
        if parent_link and clean_text(parent_link.get_text(" ", strip=True)) == title:
            parent_link.decompose()
        else:
            fragment_title.decompose()
    for element in fragment.select(".post-date, script, style"):
        element.decompose()

    for element in fragment.find_all(id=True):
        if element.name != "a":
            anchor = fragment.new_tag("a", id=element.get("id"))
            element.insert_before(anchor)

    for image in fragment.find_all("img"):
        image["src"] = normalize_url(image.get("src", ""))
    for link in fragment.find_all("a", href=True):
        link["href"] = normalize_url(link.get("href", ""))
        footnote_number = clean_text(link.get_text(" ", strip=True)).strip("[]")
        if footnote_number.isdigit():
            if re.fullmatch(r"#_ftn\d+", link["href"]):
                link["href"] = f"#_ftn{footnote_number}"
            elif re.fullmatch(r"#_ftnref\d+", link["href"]):
                link["href"] = f"#_ftnref{footnote_number}"
            anchor_name = link.get("name", "")
            if re.fullmatch(r"_ftnref\d+", anchor_name):
                link["name"] = f"_ftnref{footnote_number}"
            elif re.fullmatch(r"_ftn\d+", anchor_name):
                link["name"] = f"_ftn{footnote_number}"

    body = ReignitionConverter(
        heading_style="ATX",
        bullets="-",
        strip=["section"],
        wrap=False,
    ).convert_soup(fragment)
    body = body.replace("\xa0", " ").strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return Page(title=title, kind="article", source_url=source_url, date=date, body=body)


def parse_structural(section: Tag, soup: BeautifulSoup) -> Page:
    node = Page(
        title=section_title(section, soup),
        kind=section_kind(section),
        source_id=section.get("id", ""),
    )
    for child in section.find_all("section", recursive=False):
        kind = section_kind(child)
        if kind == "post":
            node.children.append(post_to_page(child))
        elif kind in STRUCTURAL_KINDS:
            node.children.append(parse_structural(child, soup))
    return node


def parse_tome(number: int, roman_title: str, title: str, subtitle: str) -> Page:
    source = SOURCE_ROOT / f"tome{number}.html"
    soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
    tome = Page(title=f"{roman_title} · {title}", kind="tome")
    tome.source_id = subtitle
    body = soup.body
    if not body:
        raise ValueError(f"No body found in {source}")
    for section in body.find_all("section", recursive=False):
        if section_kind(section) in STRUCTURAL_KINDS:
            tome.children.append(parse_structural(section, soup))
    return tome


def unique_slug(title: str, used: set[str]) -> str:
    base = slugify(title)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def assign_paths(node: Page, directory: Path) -> None:
    node.path = directory / "index.md"
    used_directories: set[str] = set()
    used_articles: set[str] = set()
    article_number = 0
    for child in node.children:
        if child.kind == "article":
            article_number += 1
            slug = unique_slug(child.title, used_articles)
            child.path = directory / f"{article_number:03d}-{slug}.md"
        else:
            slug = unique_slug(child.title, used_directories)
            assign_paths(child, directory / slug)


def relative_link(source: Path, target: Path) -> str:
    return os.path.relpath(target, start=source.parent).replace(os.sep, "/")


def frontmatter(title: str, description: str = "") -> str:
    fields = ["---", f"title: {yaml_string(title)}"]
    if description:
        fields.append(f"description: {yaml_string(description)}")
    fields.extend(["---", ""])
    return "\n".join(fields)


def write_article(page: Page, parents: list[Page]) -> None:
    assert page.path is not None
    breadcrumb = " / ".join(parent.title for parent in parents[1:])
    meta_parts = [part for part in (breadcrumb, page.date) if part]
    content = [frontmatter(page.title), f"# {page.title}", ""]
    if meta_parts:
        content.extend([f'<p class="article-meta">{" · ".join(meta_parts)}</p>', ""])
    if page.source_url:
        content.extend([f'[Read the original post ↗]({page.source_url}){{ .article-source }}', ""])
    content.extend([page.body, ""])
    page.path.parent.mkdir(parents=True, exist_ok=True)
    page.path.write_text("\n".join(content), encoding="utf-8")


def write_index(node: Page, parents: list[Page]) -> None:
    assert node.path is not None
    node.path.parent.mkdir(parents=True, exist_ok=True)
    is_tome = node.kind == "tome"
    description = node.source_id if is_tome else f"Browse {node.title} in the Reignition online edition."
    content = [frontmatter(node.title, description), f"# {node.title}", ""]
    if is_tome:
        tome_number = parents[0].title.split(" · ", 1)[0]
        content.extend(
            [
                f'<p class="tome-kicker">{tome_number}</p>',
                "",
                node.source_id,
                "",
            ]
        )

    if node.children:
        label = "Contents" if is_tome else f"In this {node.kind}"
        content.extend([f"## {label}", "", '<div class="section-list" markdown>', ""])
        for child in node.children:
            assert child.path is not None
            detail = f" — {child.date}" if child.kind == "article" and child.date else ""
            content.append(f"- [{child.title}]({relative_link(node.path, child.path)}){detail}")
        content.extend(["", "</div>", ""])

    node.path.write_text("\n".join(content), encoding="utf-8")
    for child in node.children:
        if child.kind == "article":
            write_article(child, parents + [node])
        else:
            write_index(child, parents + [node])


def article_count(node: Page) -> int:
    return sum(1 if child.kind == "article" else article_count(child) for child in node.children)


def write_home(tomes: Iterable[Page]) -> None:
    cards: list[str] = []
    for number, tome in enumerate(tomes, start=1):
        roman, title = tome.title.split(" · ", 1)
        cards.extend(
            [
                f'<a class="tome-card" href="tome-{number}/">',
                f'  <img src="assets/covers/tome-{number}.png" alt="Cover of {roman}: {title}">',
                '  <span class="tome-card__copy">',
                f'    <span class="tome-card__number">{roman}</span>',
                f'    <span class="tome-card__title">{title}</span>',
                f'    <span class="tome-card__subtitle">{tome.source_id}</span>',
                "  </span>",
                "</a>",
            ]
        )
    total = sum(article_count(tome) for tome in tomes)
    content = [
        frontmatter(
            "Reignition",
            "A navigable online edition of Nick Land's writings from 2011 onward.",
        ),
        "# Reignition",
        "",
        '<p class="tome-kicker">Nick Land’s writings · 2011–</p>',
        "",
        f"A four-tome online edition of {total:,} texts, edited by Uriel Fiori. ",
        "Read in sequence through the table of contents, move between adjacent texts ",
        "with the page navigation, or search the complete collection.",
        "",
        "[Begin with the editor’s introduction →](editors-introduction.md){ .editor-intro-link }",
        "",
        "[Download PDF and EPUB editions →](downloads.md){ .editor-intro-link }",
        "",
        '<div class="tome-grid">',
        *cards,
        "</div>",
        "",
    ]
    (DOCS_ROOT / "index.md").write_text("\n".join(content), encoding="utf-8")


def nav_entries(node: Page) -> list[tuple[str, object]]:
    assert node.path is not None
    entries: list[tuple[str, object]] = [("Overview", node.path.relative_to(DOCS_ROOT).as_posix())]
    for child in node.children:
        assert child.path is not None
        if child.kind == "article":
            entries.append((child.title, child.path.relative_to(DOCS_ROOT).as_posix()))
        else:
            entries.append((child.title, nav_entries(child)))
    return entries


def render_nav(entries: list[tuple[str, object]], indent: int = 2) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for title, value in entries:
        if isinstance(value, str):
            lines.append(f"{prefix}- {yaml_string(title)}: {value}")
        else:
            lines.append(f"{prefix}- {yaml_string(title)}:")
            lines.extend(render_nav(value, indent + 4))
    return lines


def write_config(tomes: list[Page]) -> None:
    nav: list[tuple[str, object]] = [
        ("Home", "index.md"),
        ("Editor’s Introduction", "editors-introduction.md"),
        ("Downloads", "downloads.md"),
    ]
    nav.extend((tome.title, nav_entries(tome)) for tome in tomes)
    config = [
        "# Generated by site/generate.py. Edit the generator, not this navigation.",
        "site_name: Reignition",
        "site_description: A navigable online edition of Nick Land's writings from 2011 onward.",
        "site_url: https://cyborg-nomade.github.io/reignition/",
        "repo_url: https://github.com/cyborg-nomade/reignition",
        "repo_name: cyborg-nomade/reignition",
        "docs_dir: docs",
        "site_dir: build",
        "use_directory_urls: true",
        "strict: true",
        "theme:",
        "  name: material",
        "  language: en",
        "  features:",
        "    - navigation.tabs",
        "    - navigation.sections",
        "    - navigation.indexes",
        "    - navigation.prune",
        "    - navigation.top",
        "    - navigation.footer",
        "    - search.suggest",
        "    - search.highlight",
        "    - search.share",
        "    - content.action.edit",
        "  palette:",
        "    - media: \"(prefers-color-scheme: light)\"",
        "      scheme: default",
        "      primary: black",
        "      accent: deep orange",
        "      toggle:",
        "        icon: material/weather-night",
        "        name: Use dark mode",
        "    - media: \"(prefers-color-scheme: dark)\"",
        "      scheme: slate",
        "      primary: black",
        "      accent: deep orange",
        "      toggle:",
        "        icon: material/weather-sunny",
        "        name: Use light mode",
        "plugins:",
        "  - search:",
        "      lang: en",
        "markdown_extensions:",
        "  - attr_list",
        "  - footnotes",
        "  - md_in_html",
        "  - sane_lists",
        "  - tables",
        "  - toc:",
        "      permalink: true",
        "extra_css:",
        "  - stylesheets/extra.css",
        "copyright: Edited by Uriel Fiori",
        "nav:",
        *render_nav(nav),
        "",
    ]
    (SITE_ROOT / "mkdocs.yml").write_text("\n".join(config), encoding="utf-8")


def clear_generated_content() -> None:
    for path in GENERATED_ROOTS:
        if path.exists():
            shutil.rmtree(path)
    covers = DOCS_ROOT / "assets" / "covers"
    if covers.exists():
        shutil.rmtree(covers)
    (DOCS_ROOT / "index.md").unlink(missing_ok=True)


def copy_covers() -> None:
    covers = DOCS_ROOT / "assets" / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    for number in range(1, 5):
        shutil.copy2(SOURCE_ROOT / f"tome{number}-cover.png", covers / f"tome-{number}.png")


def main() -> None:
    missing = [str(SOURCE_ROOT / f"tome{number}.html") for number in range(1, 5) if not (SOURCE_ROOT / f"tome{number}.html").exists()]
    if missing:
        raise FileNotFoundError("Missing tome sources: " + ", ".join(missing))

    clear_generated_content()
    tomes = [parse_tome(*metadata) for metadata in TOMES]
    for number, tome in enumerate(tomes, start=1):
        assign_paths(tome, DOCS_ROOT / f"tome-{number}")
        write_index(tome, [tome])
    copy_covers()
    write_home(tomes)
    write_config(tomes)

    structural_pages = sum(
        1
        for path in DOCS_ROOT.glob("tome-*/**/index.md")
        if path.is_file()
    )
    article_pages = sum(article_count(tome) for tome in tomes)
    print(f"Generated {article_pages} articles and {structural_pages} contents pages across four tomes.")


if __name__ == "__main__":
    main()
