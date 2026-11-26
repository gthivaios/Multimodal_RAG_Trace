"""Turn raw scraped records into clean, uniform document records.

What changes compared with the raw Stage 1 record:
  * text is normalised (unicode NFC, unified quotes, collapsed whitespace);
  * Latin look-alike letters inside Greek words are fixed (e.g. "Oι" -> "Οι");
  * every image gets a stable ``image_id`` and a path that actually exists on
    disk (old records stored Windows paths such as ``trace_data\\images\\x.jpg``);
  * scraping-only fields (``schema_version``, empty OCR placeholders) are dropped.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from trace_rag import config
from trace_rag.taxonomy import map_racism_structure

# Latin capitals that look identical to Greek capitals. Typing mistakes like
# "Oι" (Latin O + Greek ι) break exact-match search, so we fix them when the
# letter sits next to a Greek letter.
_LATIN_TO_GREEK = str.maketrans({
    "A": "Α", "B": "Β", "E": "Ε", "H": "Η", "I": "Ι", "K": "Κ", "M": "Μ",
    "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ", "Z": "Ζ",
    "o": "ο",
})
_GREEK = r"[Ͱ-Ͽἀ-῿]"
_MIXED_TOKEN = re.compile(rf"\b(?=\w*{_GREEK})(?=\w*[A-Za-z])\w+\b")


def _fix_mixed_script(text: str) -> str:
    def repl(match: re.Match) -> str:
        token = match.group(0)
        greek = sum(bool(re.match(_GREEK, ch)) for ch in token)
        # Only translate when the token is mostly Greek.
        return token.translate(_LATIN_TO_GREEK) if greek >= len(token) / 2 else token

    return _MIXED_TOKEN.sub(repl, text)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[“”«»„]", '"', text)
    text = re.sub(r"[‘’‛]", "'", text)
    text = _fix_mixed_script(text)
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def resolve_image_path(stored_path: str) -> Path | None:
    """Find an image on disk whatever form its stored path has."""
    filename = Path(stored_path.replace("\\", "/")).name
    candidate = config.RAW_IMAGE_DIR / filename
    return candidate if candidate.exists() else None


def build_document(raw: dict) -> dict:
    doc_id = int(raw["document_id"])
    racism_structure = {
        normalize_text(cat): [normalize_text(m) for m in means]
        for cat, means in (raw.get("racism_structure") or {}).items()
    }
    images = []
    urls = raw.get("image_urls") or []
    local_paths = raw.get("image_local_paths") or []
    alts = raw.get("image_alt_texts") or []
    titles = raw.get("image_titles") or []

    for index, url in enumerate(urls):
        # local paths are only written for successfully downloaded images, so
        # match them by the "_NN" index in the file name, not by list position.
        expected_prefix = f"trace_{doc_id:04d}_{index + 1:02d}"
        local = next((p for p in local_paths if expected_prefix in p), None)
        path = resolve_image_path(local) if local else None
        images.append({
            "image_id": f"doc{doc_id:04d}_img{index + 1:02d}",
            "url": url,
            "path": path.relative_to(config.PROJECT_ROOT).as_posix() if path else None,
            "alt": alts[index] if index < len(alts) else None,
            "title": titles[index] if index < len(titles) else None,
        })

    return {
        "doc_id": doc_id,
        "title": normalize_text(raw.get("title")),
        "text": normalize_text(raw.get("text")),
        "trace_url": raw.get("trace_url"),
        "original_url": raw.get("original_url"),
        "publication_date": raw.get("publication_date"),
        "language": raw.get("language"),
        "word_count": raw.get("word_count"),
        "source": raw.get("source"),
        "author_info": raw.get("author_info"),
        "text_genre": raw.get("text_genre"),
        "narrativity": raw.get("narrativity"),
        "humor": raw.get("humor"),
        "public_sphere_sector": raw.get("public_sphere_sector"),
        "public_sphere_types": raw.get("public_sphere_types") or [],
        "modality": raw.get("modality"),
        "modality_types": raw.get("modality_types") or [],
        # TRACE annotation (the labels we want to explain later)
        "racism_type": raw.get("racism_type"),
        "racism_categories": raw.get("racism_categories") or [],
        "linguistic_means": [normalize_text(m) for m in raw.get("linguistic_means") or []],
        "racism_structure": racism_structure,
        # expert grouping of the indicators (see trace_rag/taxonomy.py)
        "broader_racism_subcategories": map_racism_structure(racism_structure)[0],
        "images": images,
    }


def build_documents(raw_records: list[dict]) -> list[dict]:
    # Keep the last record per id (the checkpoint may contain re-scrapes).
    latest = {int(r["document_id"]): r for r in raw_records}
    return [build_document(latest[k]) for k in sorted(latest)]
