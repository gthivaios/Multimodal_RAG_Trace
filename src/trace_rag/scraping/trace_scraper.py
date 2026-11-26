"""Stage 1 - Scrape the TRACE wiki (https://trace.library.upatras.gr).

Pipeline:
    1. Walk the category page "Κατηγορία:Κείμενα" (with pagination) and collect
       every document title.
    2. For each document page, extract
         - the main text (everything under the "Κείμενο" heading),
         - the metadata table (racism categories, linguistic means, modality ...),
         - the content images, which are also downloaded.
    3. Append every record to a JSONL checkpoint (resumable), then export
       CSV + Parquet.

See docs/01_corpus_acquisition.md for a full explanation.
"""

from __future__ import annotations

import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

from trace_rag import config
from trace_rag.taxonomy import map_racism_structure

# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://trace.library.upatras.gr"
# "Κατηγορία:Κείμενα" (Category: Texts), percent-encoded.
CATEGORY_URL = (
    "https://trace.library.upatras.gr/wiki/"
    "%CE%9A%CE%B1%CF%84%CE%B7%CE%B3%CE%BF%CF%81%CE%AF%CE%B1:"
    "%CE%9A%CE%B5%CE%AF%CE%BC%CE%B5%CE%BD%CE%B1"
)

REQUEST_DELAY = 0.40          # seconds between requests (polite crawling)
REQUEST_TIMEOUT = 40
USER_AGENT = (
    "TRACE-Academic-Corpus-Scraper/1.0 "
    "(academic research; polite rate-limited crawler)"
)
SCHEMA_VERSION = 3            # bump to force a full re-scrape
MIN_EXPECTED_DOCUMENTS = 800  # the corpus has ~830 texts

KNOWN_METADATA_FIELDS = {
    "Link Κειμένου",
    "Ημερομηνία Δημοσίευσης",
    "Γλώσσα",
    "Αριθμός Λέξεων Κειμένου",
    "Ρευστός Ρατσισμός",
    "Κατηγορίες Ρατσισμού",
    "Τομέας της Δημόσιας Σφαίρας",
    "Πηγή Προέλευσης",
    "Συγγραφικές Πληροφορίες",
    "Τροπικότητα",
    "Αφηγηματικότητα",
    "Χιούμορ",
    "Κειμενικό Είδος",
}

NAMESPACE_PREFIXES = (
    "Κατηγορία:", "Category:", "Special:", "Ειδικό:", "Help:", "Βοήθεια:",
)

VALID_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def normalize_label(value: str | None) -> str:
    return (clean_text(value) or "").rstrip(":").strip()


def build_trace_url(title: str) -> str:
    """Build a page URL from its visible title.

    The title is fully percent-encoded (``safe=""``) so that a trailing Greek
    question mark ``;`` becomes ``%3B`` instead of being treated as a URL
    delimiter. Example: ``Έχεις αναπτήρα;`` -> ``.../%CE%B1%3B``.
    """
    return f"{BASE_URL}/wiki/{quote(title.replace(' ', '_'), safe='')}"


# ============================================================
# HTTP
# ============================================================

def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5, connect=5, read=5, backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "el,en;q=0.8"})
    return session


def fetch_page(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


# ============================================================
# DISCOVERY: category page -> list of document titles/URLs
# ============================================================

def extract_category_links(soup: BeautifulSoup) -> list[dict[str, str]]:
    pages, seen = [], set()
    for container in soup.select(".mw-category, .mw-category-generated"):
        for anchor in container.find_all("a", href=True):
            title = clean_text(anchor.get_text(" ", strip=True))
            if not title or title.startswith(NAMESPACE_PREFIXES) or title in seen:
                continue
            seen.add(title)
            pages.append({"title": title, "url": build_trace_url(title)})
    return pages


def find_next_category_page(soup: BeautifulSoup) -> str | None:
    for anchor in soup.find_all("a", href=True):
        text = (clean_text(anchor.get_text(" ", strip=True)) or "").lower()
        if "επόμενη σελίδα" in text or "next page" in text:
            return urljoin(BASE_URL, anchor["href"])
    return None


def get_all_trace_pages(session: requests.Session) -> list[dict[str, Any]]:
    """Return every document of the category, with a stable sequential id."""
    current_url: str | None = CATEGORY_URL
    all_pages: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_category_pages: set[str] = set()

    while current_url and current_url not in seen_category_pages:
        seen_category_pages.add(current_url)
        soup = fetch_page(session, current_url)
        for page in extract_category_links(soup):
            if page["title"] not in seen_titles:
                seen_titles.add(page["title"])
                all_pages.append(page)
        current_url = find_next_category_page(soup)
        time.sleep(REQUEST_DELAY)

    # The id depends on the category order of the wiki, which is alphabetical.
    for index, page in enumerate(all_pages, start=1):
        page["document_id"] = index
    return all_pages


# ============================================================
# DOCUMENT PAGE: text
# ============================================================

def find_content_root(soup: BeautifulSoup) -> Tag:
    content = soup.select_one(".mw-parser-output")
    if content is None:
        raise ValueError("Could not find .mw-parser-output")
    return content


def find_text_heading(content: Tag) -> Tag | None:
    heading = content.find(id="Κείμενο")
    if heading is not None:
        return heading
    for tag in content.find_all(["h2", "h3"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if text and text.startswith("Κείμενο"):
            return tag
    return None


def is_metadata_start(element: Tag) -> bool:
    """The metadata table always starts with the "Link Κειμένου" label."""
    if element.name not in {"th", "td", "div", "span", "p"}:
        return False
    return clean_text(element.get_text(" ", strip=True)) == "Link Κειμένου"


def iter_text_section(content: Tag):
    """Yield every Tag between the "Κείμενο" heading and the metadata / next h2."""
    heading = find_text_heading(content)
    if heading is None:
        return
    started = False
    for element in content.descendants:
        if element is heading:
            started = True
            continue
        if not started or not isinstance(element, Tag):
            continue
        if is_metadata_start(element) or element.name == "h2":
            break
        yield element


def extract_main_text(content: Tag) -> str | None:
    blocks: list[str] = []
    for element in iter_text_section(content):
        if element.name not in {"p", "li", "blockquote"}:
            continue
        if element.find_parent(["p", "li", "blockquote"]):  # avoid nested duplicates
            continue
        text = clean_text(element.get_text(" ", strip=True))
        if text and text not in blocks:
            blocks.append(text)
    return "\n\n".join(blocks) if blocks else None


# ============================================================
# DOCUMENT PAGE: metadata table
# ============================================================

def find_metadata_table(content: Tag) -> Tag | None:
    """Pick the table that contains the most known metadata labels (>= 3)."""
    best_table, best_score = None, 0
    for table in content.find_all("table"):
        table_text = table.get_text(" ", strip=True)
        score = sum(field in table_text for field in KNOWN_METADATA_FIELDS)
        if score > best_score:
            best_table, best_score = table, score
    return best_table if best_score >= 3 else None


def parse_metadata_table(table: Tag | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if table is None:
        return result
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = normalize_label(cells[0].get_text(" ", strip=True))
        if not label:
            continue
        value_cell = cells[1]
        links = [
            {
                "text": clean_text(a.get_text(" ", strip=True)),
                "url": urljoin(BASE_URL, a["href"]),
            }
            for a in value_cell.find_all("a", href=True)
        ]
        result[label] = {
            "value": clean_text(value_cell.get_text(" ", strip=True)),
            "links": links,
            "cell": value_cell,
        }
    return result


def metadata_value(metadata: dict, key: str) -> str | None:
    item = metadata.get(key)
    return item.get("value") if item else None


def first_external_link(metadata: dict, key: str) -> str | None:
    """Prefer a link that points outside the wiki (the original publication)."""
    item = metadata.get(key)
    if not item:
        return None
    links = item.get("links", [])
    for link in links:
        if not link["url"].startswith(BASE_URL):
            return link["url"]
    return links[0]["url"] if links else None


def parse_parenthesized_links(cell: Tag | None) -> tuple[list[str], dict[str, list[str]]]:
    """Parse cells shaped like ``A (x, y), B (z)`` into ``[A, B]`` and ``{A: [x, y], B: [z]}``.

    Links outside parentheses are primary categories; links inside parentheses
    are the sub-items of the most recent primary category.
    """
    if cell is None:
        return [], {}
    depth = 0
    primary: list[str] = []
    mapping: dict[str, list[str]] = {}
    current_primary = None

    for element in cell.descendants:
        if isinstance(element, NavigableString):
            if element.parent and element.parent.name == "a":
                continue
            for char in str(element):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth = max(0, depth - 1)
        elif isinstance(element, Tag) and element.name == "a":
            label = clean_text(element.get_text(" ", strip=True))
            if not label:
                continue
            if depth == 0:
                current_primary = label
                if label not in primary:
                    primary.append(label)
                mapping.setdefault(label, [])
            elif current_primary and label not in mapping[current_primary]:
                mapping[current_primary].append(label)
    return primary, mapping


def get_hierarchy(metadata: dict, key: str) -> tuple[list[str], dict[str, list[str]]]:
    item = metadata.get(key)
    return parse_parenthesized_links(item["cell"]) if item else ([], {})


def extract_primary_and_subtypes(metadata: dict, key: str) -> tuple[str | None, list[str]]:
    primary, mapping = get_hierarchy(metadata, key)
    if primary:
        return primary[0], mapping.get(primary[0], [])
    return metadata_value(metadata, key), []


def parse_integer(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d[\d.,]*", value)
    if not match:
        return None
    number = re.sub(r"[^\d]", "", match.group(0))
    return int(number) if number else None


# ============================================================
# DOCUMENT PAGE: images
# ============================================================

def is_content_image(img: Tag) -> bool:
    src = (img.get("src") or "").lower()
    if not src or any(t in src for t in ("logo", "icon", "button", "poweredby", "wikimedia")):
        return False

    def _dim(attr: str) -> int:
        match = re.search(r"\d+", str(img.get(attr, "")))
        return int(match.group()) if match else 0

    width, height = _dim("width"), _dim("height")
    return not (width and height and width < 80 and height < 80)


def extract_images(content: Tag) -> list[dict[str, Any]]:
    images, seen = [], set()
    for element in iter_text_section(content):
        if element.name != "img" or not is_content_image(element):
            continue
        src = element.get("src")
        image_url = "https:" + src if src.startswith("//") else urljoin(BASE_URL, src)
        if image_url in seen:
            continue
        seen.add(image_url)
        images.append({
            "url": image_url,
            "alt": clean_text(element.get("alt")),
            "title": clean_text(element.get("title")),
        })
    return images


def download_images(
    session: requests.Session, images: list[dict[str, Any]], document_id: int
) -> list[str]:
    """Download images to data/raw/images and return paths *relative to data/raw*."""
    local_paths = []
    for image_index, image in enumerate(images, start=1):
        try:
            response = session.get(image["url"], stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            )
            if content_type and not content_type.startswith("image/"):
                continue

            suffix = Path(urlparse(image["url"]).path).suffix.lower()
            if suffix not in VALID_IMAGE_EXTENSIONS:
                suffix = mimetypes.guess_extension(content_type) or ".jpg"
            if suffix == ".jpe":
                suffix = ".jpg"

            filename = f"trace_{document_id:04d}_{image_index:02d}{suffix}"
            with (config.RAW_IMAGE_DIR / filename).open("wb") as file:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        file.write(chunk)
            # POSIX-style relative path: portable across OSes and folder moves.
            local_paths.append(f"images/{filename}")
        except Exception as exc:  # noqa: BLE001 - one bad image must not stop the run
            tqdm.write(
                f"WARNING: image download failed for document {document_id}, "
                f"image {image_index}: {exc}"
            )
    return local_paths


# ============================================================
# ONE DOCUMENT -> ONE RECORD
# ============================================================

def parse_document(
    session: requests.Session, page: dict[str, Any], download: bool = True
) -> dict[str, Any]:
    soup = fetch_page(session, page["url"])
    content = find_content_root(soup)

    text = extract_main_text(content)
    if not text:
        raise ValueError("No text extracted")

    metadata_table = find_metadata_table(content)
    if metadata_table is None:
        raise ValueError("Metadata table not found")
    metadata = parse_metadata_table(metadata_table)

    # Racism categories -> linguistic means (indicators), e.g.
    # {"Διάκριση": ["Αναφορές στους ‘άλλους’ ως θύματα", ...], "Αφομοίωση": [...]}
    racism_categories, racism_structure = get_hierarchy(metadata, "Κατηγορίες Ρατσισμού")
    linguistic_means: list[str] = []
    for indicators in racism_structure.values():
        for indicator in indicators:
            if indicator not in linguistic_means:
                linguistic_means.append(indicator)

    public_sphere_sector, public_sphere_types = extract_primary_and_subtypes(
        metadata, "Τομέας της Δημόσιας Σφαίρας"
    )
    modality, modality_types = extract_primary_and_subtypes(metadata, "Τροπικότητα")

    images = extract_images(content)
    image_local_paths = (
        download_images(session, images, page["document_id"]) if download and images else []
    )

    return {
        "schema_version": SCHEMA_VERSION,
        # main content
        "document_id": page["document_id"],
        "title": page["title"],
        "text": text,
        # basic metadata
        "original_url": first_external_link(metadata, "Link Κειμένου"),
        "trace_url": page["url"],
        "publication_date": metadata_value(metadata, "Ημερομηνία Δημοσίευσης"),
        "language": metadata_value(metadata, "Γλώσσα"),
        "word_count": parse_integer(metadata_value(metadata, "Αριθμός Λέξεων Κειμένου")),
        # racism annotation
        "racism_type": metadata_value(metadata, "Ρευστός Ρατσισμός"),
        "racism_categories": racism_categories,
        "linguistic_means": linguistic_means,
        "racism_structure": racism_structure,
        "broader_racism_subcategories": map_racism_structure(racism_structure)[0],
        # public sphere
        "public_sphere_sector": public_sphere_sector,
        "public_sphere_types": public_sphere_types,
        # origin
        "source": metadata_value(metadata, "Πηγή Προέλευσης"),
        "author_info": metadata_value(metadata, "Συγγραφικές Πληροφορίες"),
        # modality
        "modality": modality,
        "modality_types": modality_types,
        # other annotation
        "narrativity": metadata_value(metadata, "Αφηγηματικότητα"),
        "humor": metadata_value(metadata, "Χιούμορ"),
        "text_genre": metadata_value(metadata, "Κειμενικό Είδος"),
        # images
        "image_urls": [img["url"] for img in images],
        "image_local_paths": image_local_paths,
        "image_alt_texts": [img["alt"] for img in images],
        "image_titles": [img["title"] for img in images],
        "image_count": len(images),
        # filled in Stage 2 (data/processed/images.jsonl), kept for schema stability
        "image_ocr_texts": [],
        "image_descriptions": [],
    }


# ============================================================
# CHECKPOINT + EXPORT
# ============================================================

def append_jsonl(filepath: Path, record: dict) -> None:
    with filepath.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(filepath: Path) -> list[dict]:
    if not filepath.exists():
        return []
    records = []
    with filepath.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def record_is_complete(record: dict) -> bool:
    if record.get("schema_version") != SCHEMA_VERSION:
        return False
    required = ["document_id", "title", "text", "racism_structure", "image_urls"]
    return all(record.get(field) is not None for field in required)


def add_broader_subcategories(record: dict) -> dict:
    """(Re)compute ``broader_racism_subcategories`` and place it right after ``racism_structure``.

    It is derived only from ``racism_structure``, so older checkpoint records
    are upgraded in place without fetching the page again.
    """
    broader, _ = map_racism_structure(record.get("racism_structure") or {})
    upgraded = {}
    for key, value in record.items():
        if key == "broader_racism_subcategories":
            continue
        upgraded[key] = value
        if key == "racism_structure":
            upgraded["broader_racism_subcategories"] = broader
    return upgraded


def rewrite_jsonl(filepath: Path, records: list[dict]) -> None:
    """Atomically replace the checkpoint with deduplicated, sorted records."""
    tmp = filepath.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(filepath)


def export_records(records: list[dict]) -> None:
    """Write one row per document to CSV (Excel-friendly) and Parquet."""
    if not records:
        print("No successful records to export.")
        return
    unique = {record["document_id"]: record for record in records}
    records = sorted(unique.values(), key=lambda r: r["document_id"])

    df = pd.DataFrame(records)
    # CSV/Parquet cannot hold nested Python objects uniformly -> JSON strings.
    for column in df.columns:
        if df[column].map(lambda v: isinstance(v, (dict, list))).any():
            df[column] = df[column].map(
                lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            )
    df.to_csv(config.RAW_CSV, index=False, encoding="utf-8-sig")
    df.to_parquet(config.RAW_PARQUET, index=False)


def print_quality_report(pages: list[dict], records: list[dict]) -> None:
    def missing(field: str) -> int:
        return sum(not r.get(field) for r in records)

    successful = len({r["document_id"] for r in records})
    text_lengths = [len(r["text"]) for r in records if r.get("text")]
    rows = [
        ("Documents targeted", len(pages)),
        ("Successfully scraped", successful),
        ("Failed / not scraped", len(pages) - successful),
        ("Documents without images", missing("image_urls")),
        ("Documents with >1 image", sum(r.get("image_count", 0) > 1 for r in records)),
        ("Total images detected", sum(r.get("image_count", 0) for r in records)),
        ("Total images downloaded", sum(len(r.get("image_local_paths", [])) for r in records)),
        ("Missing racism categories", missing("racism_categories")),
        ("Missing modality", missing("modality")),
        ("Missing broader subcategories", missing("broader_racism_subcategories")),
    ]
    unmapped = sorted({
        pair for r in records
        for pair in map_racism_structure(r.get("racism_structure") or {})[1]
    })
    if text_lengths:
        rows += [
            ("Shortest text (chars)", min(text_lengths)),
            ("Longest text (chars)", max(text_lengths)),
            ("Average text (chars)", sum(text_lengths) // len(text_lengths)),
        ]
    print("\n" + "=" * 60 + "\nTRACE SCRAPING SUMMARY\n" + "=" * 60)
    for label, value in rows:
        print(f"{label:<32}{value}")
    if unmapped:
        print("WARNING: indicators without a broader subcategory (add a rule in taxonomy.py):")
        for category, indicator in unmapped:
            print(f"  - {category}: {indicator}")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

def run(limit: int | None = None, download_images_flag: bool = True) -> None:
    config.RAW_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    session = create_session()

    print("Retrieving TRACE document list...")
    pages = get_all_trace_pages(session)
    print(f"TRACE pages discovered: {len(pages)}")

    # Safety check on the *full* list, before any --limit is applied.
    if len(pages) < MIN_EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"Only {len(pages)} documents discovered (~830 expected). "
            "Stopping to avoid an incomplete corpus."
        )

    if limit:
        pages = pages[:limit]
        print(f"--limit {limit}: scraping only the first {len(pages)} documents")

    records = [
        add_broader_subcategories(r) for r in load_jsonl(config.RAW_JSONL) if record_is_complete(r)
    ]
    completed_ids = {r["document_id"] for r in records}
    remaining = [p for p in pages if p["document_id"] not in completed_ids]
    print(f"Already completed: {len(completed_ids)} | Remaining: {len(remaining)}")

    for page in tqdm(remaining, desc="Scraping TRACE"):
        try:
            record = parse_document(session, page, download=download_images_flag)
            records.append(record)
            append_jsonl(config.RAW_JSONL, record)
        except Exception as exc:  # noqa: BLE001 - log and continue
            append_jsonl(config.RAW_ERRORS, {**page, "error": str(exc)})
            tqdm.write(f"ERROR [{page['document_id']}] {page['title']} -> {exc}")
        time.sleep(REQUEST_DELAY)

    target_ids = {p["document_id"] for p in pages}
    unique = sorted({r["document_id"]: r for r in records}.values(), key=lambda r: r["document_id"])
    rewrite_jsonl(config.RAW_JSONL, unique)
    export_records(unique)
    print_quality_report(pages, [r for r in records if r["document_id"] in target_ids])
    print(f"\nJSONL:   {config.RAW_JSONL}\nCSV:     {config.RAW_CSV}\nParquet: {config.RAW_PARQUET}")
