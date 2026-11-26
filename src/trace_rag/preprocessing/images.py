"""Turn every corpus image into retrievable text with a vision-language model (VLM).

For each image we ask the VLM for:
  * ``ocr_text``    - any text written inside the image (posters, banners, captions);
  * ``description`` - a neutral, factual description in Greek of what is shown
                      (who, doing what, where), with no interpretation of racism.

The description is intentionally *neutral*: the interpretation is the job of
the RAG answer later, which must remain grounded in the TRACE framework. If the
captioner already interpreted the image, retrieval would be biased.

Results are cached per file content hash, so re-running the stage only pays for
new or changed images.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from pathlib import Path

from tqdm import tqdm

from trace_rag import config
from trace_rag.io import append_jsonl, read_jsonl

# Formats accepted by the common VLM APIs. SVG/TIFF/BMP are skipped.
SUPPORTED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}

PROMPT = """Είσαι βοηθός που περιγράφει εικόνες για ένα ερευνητικό σώμα κειμένων.
Η εικόνα συνοδεύει το κείμενο με τίτλο: "{title}".

Επέστρεψε ΜΟΝΟ ένα αντικείμενο JSON με τα πεδία:
- "ocr_text": όλο το κείμενο που είναι γραμμένο μέσα στην εικόνα, αυτούσιο (ή "" αν δεν υπάρχει).
- "description": ουδέτερη, περιγραφική απόδοση στα ελληνικά (2-4 προτάσεις) του τι
  απεικονίζεται: πρόσωπα, ενέργειες, χώρος, σύμβολα. Μην ερμηνεύεις και μην αξιολογείς.
"""


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _to_data_url(path: Path) -> tuple[str | None, str | None]:
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in SUPPORTED_MIME:
        return None, mime
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}", mime


def _parse_json(content: str) -> dict:
    match = re.search(r"\{.*\}", content or "", re.S)
    if not match:
        return {"ocr_text": "", "description": (content or "").strip()}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"ocr_text": "", "description": content.strip()}
    return {
        "ocr_text": str(data.get("ocr_text") or "").strip(),
        "description": str(data.get("description") or "").strip(),
    }


def annotate_image(path: Path, title: str, model: str = config.VLM_MODEL) -> dict:
    from trace_rag.llm import get_client  # imported lazily: only needed when calling the API

    data_url, _ = _to_data_url(path)
    response = get_client().chat.completions.create(
        model=model,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT.format(title=title)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    )
    return _parse_json(response.choices[0].message.content)


def _retrieval_text(record: dict) -> str:
    """The text that represents an image in the text index (Stage 4)."""
    parts = [f"[Εικόνα από: {record['title']}]"]
    if record.get("description"):
        parts.append(f"Περιγραφή: {record['description']}")
    if record.get("ocr_text"):
        parts.append(f"Κείμενο στην εικόνα: {record['ocr_text']}")
    if record.get("alt"):
        parts.append(f"Εναλλακτικό κείμενο: {record['alt']}")
    return "\n".join(parts)


def build_image_records(documents: list[dict], annotate: bool = True) -> list[dict]:
    cache = {c["sha1"]: c for c in read_jsonl(config.IMAGE_ANNOTATION_CACHE)}
    items = [(doc, img) for doc in documents for img in doc["images"]]
    records = []
    stats = {"annotated": 0, "cached": 0, "missing_file": 0, "unsupported": 0, "failed": 0, "skipped": 0}

    for doc, img in tqdm(items, desc="Images"):
        record = {
            "image_id": img["image_id"],
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "path": img["path"],
            "url": img["url"],
            "alt": img["alt"],
            "trace_url": doc["trace_url"],
            "racism_categories": doc["racism_categories"],
            "linguistic_means": doc["linguistic_means"],
            "broader_racism_subcategories": [
                s for subs in doc["broader_racism_subcategories"].values() for s in subs
            ],
            "ocr_text": "",
            "description": "",
            "annotation_status": "pending",
        }
        if not img["path"]:
            record["annotation_status"] = "missing_file"
            stats["missing_file"] += 1
        else:
            path = config.PROJECT_ROOT / img["path"]
            mime = mimetypes.guess_type(path.name)[0]
            sha1 = _sha1(path)
            record["sha1"], record["mime"] = sha1, mime
            if mime not in SUPPORTED_MIME:
                record["annotation_status"] = "unsupported_format"
                stats["unsupported"] += 1
            elif sha1 in cache:
                record.update({k: cache[sha1][k] for k in ("ocr_text", "description", "model")})
                record["annotation_status"] = "ok"
                stats["cached"] += 1
            elif not annotate:
                record["annotation_status"] = "skipped"
                stats["skipped"] += 1
            else:
                try:
                    result = annotate_image(path, doc["title"])
                    cached = {"sha1": sha1, "model": config.VLM_MODEL, **result}
                    append_jsonl(config.IMAGE_ANNOTATION_CACHE, cached)
                    cache[sha1] = cached
                    record.update({**result, "model": config.VLM_MODEL, "annotation_status": "ok"})
                    stats["annotated"] += 1
                except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                    record["annotation_status"] = f"failed: {exc}"
                    stats["failed"] += 1
                    tqdm.write(f"WARNING {img['image_id']}: {exc}")
        record["retrieval_text"] = _retrieval_text(record)
        records.append(record)

    print("Image annotation:", ", ".join(f"{k}={v}" for k, v in stats.items()))
    return records
