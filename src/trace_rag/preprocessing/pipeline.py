"""Stage 2 entry point: raw corpus -> documents.jsonl, chunks.jsonl, images.jsonl."""

from __future__ import annotations

import statistics

from trace_rag import config
from trace_rag.io import read_jsonl, write_jsonl
from trace_rag.preprocessing.chunking import chunk_document
from trace_rag.preprocessing.documents import build_documents
from trace_rag.preprocessing.images import build_image_records


def run(annotate_images: bool = True) -> None:
    raw = read_jsonl(config.RAW_JSONL)
    if not raw:
        raise SystemExit(f"No raw corpus at {config.RAW_JSONL}. Run Stage 1 first.")

    documents = build_documents(raw)
    write_jsonl(config.DOCUMENTS_JSONL, documents)

    chunks = [chunk for doc in documents for chunk in chunk_document(doc)]
    write_jsonl(config.CHUNKS_JSONL, chunks)

    images = build_image_records(documents, annotate=annotate_images)
    write_jsonl(config.IMAGES_JSONL, images)

    lengths = [len(c["text"]) for c in chunks]
    per_doc = [len(chunk_document(d)) for d in documents]
    print("\n" + "=" * 60 + "\nSTAGE 2 SUMMARY\n" + "=" * 60)
    print(f"{'Documents':<32}{len(documents)}")
    print(f"{'Text chunks':<32}{len(chunks)}")
    print(f"{'Chunks per document (max)':<32}{max(per_doc)}")
    print(f"{'Chunk length min/median/max':<32}{min(lengths)} / {int(statistics.median(lengths))} / {max(lengths)}")
    print(f"{'Images':<32}{len(images)}")
    print(f"{'Images with annotation':<32}{sum(i['annotation_status'] == 'ok' for i in images)}")
    print("=" * 60)
    for path in (config.DOCUMENTS_JSONL, config.CHUNKS_JSONL, config.IMAGES_JSONL):
        print(path.relative_to(config.PROJECT_ROOT).as_posix())
