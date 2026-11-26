# Stage 2: Multimodal preprocessing

**Goal:** turn the raw corpus into units that can be retrieved: clean documents, text chunks, and a
**textual representation of every image**.

**Run:**
```powershell
python scripts/02_preprocess.py --no-vlm   # free and offline: documents + chunks only
python scripts/02_preprocess.py            # also OCR + describe images with the VLM (API calls)
```

**Code:** [`src/trace_rag/preprocessing/`](../src/trace_rag/preprocessing/)
**Input:** `data/raw/trace_corpus.jsonl`, `data/raw/images/`
**Output:** `data/processed/documents.jsonl`, `chunks.jsonl`, `images.jsonl`

```
raw record ──► documents.py ──► clean document ──┬─► chunking.py ──► text chunks
                                                 └─► images.py   ──► image records (VLM OCR + description)
```

## 2.1 Document cleaning (`documents.py`)

| Step | Why |
|---|---|
| Unicode NFC normalisation | Greek accents can be stored as one or two code points. NFC makes identical words identical bytes, which exact search and BM25 need. |
| Unify quotes (`‘ ’ “ ” « »` → `' "`) | The wiki mixes quote styles, also inside the indicator labels. |
| Fix Latin look-alike letters in Greek words | e.g. `Oι` (Latin O) → `Οι`. Otherwise the word never matches a Greek query. Only applied when the word is mostly Greek, so `COVID` and `UNHCR` stay unchanged. |
| Collapse whitespace, keep paragraph breaks | Paragraphs are the main chunking boundary. |
| Stable `image_id` per image (`doc0001_img01`) | Chunks, images and answers refer to images by id. |
| Resolve image paths on disk | Older records stored Windows paths (`trace_data\images\…`). The file name is resolved inside `data/raw/images/` instead. |

## 2.2 Text chunking (`chunking.py`)

Texts range from 77 to 45,000 characters. Long texts must be split: an embedding of a whole report
blurs its content, and the LLM should get focused evidence.

**Strategy:** paragraph-aware, greedy packing.

1. Split into paragraphs.
2. A paragraph longer than the limit is split into sentences. Greek punctuation is handled: `;` is the
   question mark, and `·` is the ano teleia.
3. Pack pieces into chunks of at most **1000 characters**.
4. Each chunk starts with the last **~150 characters** of the previous one (cut at a word boundary,
   marked with `…`). Evidence on a chunk boundary therefore still appears whole in one chunk.
5. A trailing piece under **200 characters** is merged into the previous chunk.

Parameters are in `src/trace_rag/config.py` (`CHUNK_*`). They are deliberately simple so they can be
tuned in Stage 6, for example by comparing retrieval recall at 500, 1000 and 1500 characters.

Each chunk **inherits the document metadata** (title, source, genre, categories, linguistic means,
image ids, URL). That allows (a) filtering, e.g. "only Αφομοίωση texts", and (b) citing the source in
the answer.

> **Important for evaluation:** the categories copied onto chunks are the expert *document-level*
> labels. They are used for filtering and for building the knowledge base. When we evaluate on held-out
> texts, the model must **not** see the labels of the test texts (see Stage 6).

## 2.3 Images: from pixels to retrievable text (`images.py`)

77 of the 99 texts are *multimodal* (Πολυτροπικό), and images carry part of the message: posters,
campaign banners, photos of migrants. To make images retrievable by the same text search, every image
is sent once to a **vision-language model** (default `google/gemini-2.5-flash` via OpenRouter, the same
model as the earlier notebooks). The VLM returns:

* `ocr_text`: the text written inside the image, verbatim;
* `description`: a **neutral** 2–4 sentence description in Greek: people, actions, setting, symbols.

The description is **descriptive, not interpretive** on purpose. Interpretation in terms of
discrimination categories happens in the RAG answer and must be grounded in the TRACE framework. If the
captioner already labelled an image "paternalistic", retrieval would be biased by an unverified
judgement.

Each image record has a `retrieval_text` (title + description + OCR + alt text). Stage 4 indexes it
alongside the text chunks.

**Robustness and cost**
* Results are cached in `image_annotations_cache.jsonl`, keyed by the **SHA-1 of the image file**.
  Re-runs only pay for new images. The 111 images of the subset are a one-off cost of a few cents with
  a Flash model.
* Unsupported formats (SVG, TIFF, BMP) are marked `unsupported_format` and do not crash the run.
* API errors are recorded per image (`annotation_status`), and the run continues.

## 2.4 Output files

| File | One line per | Key fields |
|---|---|---|
| `documents.jsonl` | text | `doc_id`, `title`, `text`, all metadata (incl. `racism_structure` and `broader_racism_subcategories` as `{category: [...]}`), `images[]` |
| `chunks.jsonl` | text chunk | `chunk_id` (`doc0001_c00`), `doc_id`, `text`, inherited metadata (incl. flat `linguistic_means` and `broader_racism_subcategories` lists, for filtering), `image_ids` |
| `images.jsonl` | image | `image_id`, `doc_id`, `path`, flat `linguistic_means` / `broader_racism_subcategories`, `ocr_text`, `description`, `retrieval_text`, `annotation_status` |

## 2.5 Results on the full corpus (`--no-vlm`, 2026-11-26)

| | |
|---|---|
| documents | 785 |
| text chunks | 4,642 |
| chunk length (min / median / max) | 30 / 821 / 1195 characters |
| images | 974, all found on disk; 0 annotated yet (run without `--no-vlm`) |

## 2.5b Earlier results on the prototype subset

| | |
|---|---|
| documents | 99 |
| text chunks | 475 |
| chunk length (min / median / max) | 77 / 795 / 999 characters |
| most chunks for one text | 69 (doc 70, a 45k-character report by the Greek Council for Refugees on the asylum bill) |
| images | 111, all found on disk |
| images annotated | 0. Run without `--no-vlm` to fill them. |
