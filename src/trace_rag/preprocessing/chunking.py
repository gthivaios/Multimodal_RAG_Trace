"""Paragraph-aware text chunking.

Strategy (simple on purpose, easy to explain and to evaluate later):
  1. Split the text into paragraphs (the scraper separates them with blank lines).
  2. Paragraphs longer than ``max_chars`` are split into sentences; a sentence
     that is still too long is hard-wrapped on whitespace.
  3. Pieces are packed greedily into chunks of at most ``max_chars``.
  4. Each new chunk starts with the last ``overlap_chars`` of the previous one
     (cut at a word boundary) so that evidence spanning a boundary is not lost.
  5. A tiny trailing chunk is merged into the previous one.

Every chunk carries the document metadata it needs for filtering and for
citing the source in the final answer.
"""

from __future__ import annotations

import re

from trace_rag import config

# Greek uses ";" as question mark and "·" (ano teleia) as a semicolon.
_SENTENCE_END = re.compile(r"(?<=[.!;?…·])\s+(?=[\"'(«]?[A-ZΑ-ΩΆΈΉΊΌΎΏ0-9])")


def _split_sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(paragraph) if s.strip()]


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    pieces, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def _atomic_pieces(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in text.split("\n\n"):
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for sentence in _split_sentences(paragraph):
            pieces.extend([sentence] if len(sentence) <= max_chars else _hard_wrap(sentence, max_chars))
    return [p for p in pieces if p]


def _tail(text: str, n_chars: int) -> str:
    if n_chars <= 0 or len(text) <= n_chars:
        return ""
    tail = text[-n_chars:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def split_text(
    text: str,
    max_chars: int = config.CHUNK_MAX_CHARS,
    min_chars: int = config.CHUNK_MIN_CHARS,
    overlap_chars: int = config.CHUNK_OVERLAP_CHARS,
) -> list[str]:
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for piece in _atomic_pieces(text, max_chars):
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(piece) <= max_chars:
            current += separator + piece
            continue
        chunks.append(current)
        overlap = _tail(current, overlap_chars)
        current = f"{overlap} … {piece}" if overlap and len(overlap) + len(piece) + 3 <= max_chars else piece
    if current:
        chunks.append(current)

    if len(chunks) > 1 and len(chunks[-1]) < min_chars:
        last = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n\n{last}"
    return chunks


def chunk_document(doc: dict, **kwargs) -> list[dict]:
    pieces = split_text(doc["text"], **kwargs)
    return [
        {
            "chunk_id": f"doc{doc['doc_id']:04d}_c{index:02d}",
            "doc_id": doc["doc_id"],
            "chunk_index": index,
            "n_chunks": len(pieces),
            "title": doc["title"],
            "text": piece,
            # metadata copied onto every chunk -> filtering + citations
            "trace_url": doc["trace_url"],
            "source": doc["source"],
            "publication_date": doc["publication_date"],
            "text_genre": doc["text_genre"],
            "modality": doc["modality"],
            "racism_categories": doc["racism_categories"],
            "linguistic_means": doc["linguistic_means"],
            "broader_racism_subcategories": [
                s for subs in doc["broader_racism_subcategories"].values() for s in subs
            ],
            "image_ids": [img["image_id"] for img in doc["images"]],
        }
        for index, piece in enumerate(pieces)
    ]
