# Stage 1: Corpus acquisition

**Goal:** collect every TRACE text with its expert annotations and images into one machine-readable
dataset.

**Run:**
```powershell
python scripts/01_scrape_corpus.py --limit 100   # prototype subset (what we use now)
python scripts/01_scrape_corpus.py               # full corpus, ~830 texts
```

**Code:** [`src/trace_rag/scraping/trace_scraper.py`](../src/trace_rag/scraping/trace_scraper.py)
**Output:** `data/raw/` (git-ignored)

## 1. How the TRACE wiki is organised

TRACE (https://trace.library.upatras.gr) is a MediaWiki. Every corpus text is one wiki page, and all of
them are listed in the category page **Κατηγορία:Κείμενα** (Category: Texts), split over several pages
("επόμενη σελίδα" = next page). Each text page has two parts:

1. a section with the heading **Κείμενο** (Text) that holds the text itself, often with images;
2. a **metadata table** that starts with *Link Κειμένου* and holds the expert annotation.

## 2. Pipeline

```
Category page ──► list of titles ──► for each page:  text  +  metadata  +  images
 (paginated)        (+ doc id)                         │          │           │
                                                       └──────────┴───────────┴─► JSONL checkpoint
                                                                                    └─► CSV + Parquet
```

### 2.1 Discovery (`get_all_trace_pages`)
* Reads every category page and follows the "next page" link until there is none.
* Skips namespace links (`Κατηγορία:`, `Special:` …).
* **URLs are rebuilt from the visible title**, fully percent-encoded (`build_trace_url`). Reason: some
  titles end with the Greek question mark `;` (e.g. *Έχεις αναπτήρα;*). In the raw `href` it can be read
  as a URL delimiter, so the page would not be found. Encoding it as `%3B` fixes this.
* Each document gets a sequential `document_id` in category (alphabetical) order.
* **Safety check:** if fewer than 800 documents are discovered, the run stops. That usually means the
  site layout changed, and we must not silently build an incomplete corpus.

### 2.2 Text extraction (`extract_main_text`)
Walks the page from the *Κείμενο* heading and collects `<p>`, `<li>` and `<blockquote>` blocks. It stops
at the metadata table or the next `<h2>`. Nested blocks and duplicates are skipped. Paragraphs are
joined with a blank line, and Stage 2 relies on that for chunking.

### 2.3 Metadata (`find_metadata_table`, `parse_metadata_table`)
The metadata table is the table that contains the most known labels (at least 3). Each row becomes
`label → {value, links}`.

The most important field is **Κατηγορίες Ρατσισμού** (racism categories). On the wiki it looks like:

```
Διάκριση (Αναφορές στους ανώνυμους 'άλλους', Αναφορές στους 'άλλους' ως θύματα), Αφομοίωση (...)
```

`parse_parenthesized_links` counts parentheses: links outside them are **categories**, and links inside
them are the **linguistic means** (indicators) of that category:

```json
"racism_structure": {
  "Διάκριση":  ["Αναφορές στους ανώνυμους 'άλλους'", "Αναφορές στους 'άλλους' ως θύματα"],
  "Αφομοίωση": ["Αναφορές στον όρο 'ένταξη/ενσωμάτωση' ..."]
}
```

#### Broader racism subcategories (`broader_racism_subcategories`)
Right after `racism_structure`, each record has the expert grouping of the 11 indicators into 5 broader
subcategories ([`src/trace_rag/taxonomy.py`](../src/trace_rag/taxonomy.py)):

| Category | Indicator | Broader subcategory |
|---|---|---|
| Διάκριση | Άλλοι/ες ως πρόβλημα · παράνομοι/ες ή/και νόμιμοι/ες Άλλοι/ες | Ο/Η Άλλος/η ως πρόβλημα |
| Διάκριση | ανώνυμοι/ες Άλλοι/ες · προσωρινοί/ές Άλλοι/ες | Ο/Η απομακρυσμένος/η Άλλος/η |
| Διάκριση | αδρανείς Άλλοι/ες · Άλλοι/ες ως θύματα · Άλλοι/ες ως αποδέκτες/τριες βοήθειας | Ο/Η παθητικός/η Άλλος/η |
| Αφομοίωση | πρακτικές ένταξης/ενσωμάτωσης · μετριασμένοι τρόποι αντίκρουσης του ρατσισμού | Ασθενής αφομοίωση |
| Αφομοίωση | πρακτικές εκμάθησης ελληνικών · θετική στάση μεταναστών/τριών & προσφύγων/ισσών σε αφομοιωτικές πρακτικές | Ισχυρή αφομοίωση |

```json
"broader_racism_subcategories": {
  "Διάκριση":  ["Ο/Η απομακρυσμένος/η Άλλος/η", "Ο/Η παθητικός/η Άλλος/η"],
  "Αφομοίωση": ["Ασθενής αφομοίωση"]
}
```

The wiki labels are not written exactly like the expert list (`Αναφορές στους αδρανείς ‘άλλους’` vs
`Αναφορές στους/στις αδρανείς Άλλους/ες`). So indicators are matched by a key phrase after
normalisation (lower case, no accents, no quotes). The field depends only on `racism_structure`, so
existing checkpoint records are upgraded on the next run without fetching them again. Any indicator
with no rule is printed as a WARNING in the scraping summary.

The same parser gives *Τομέας της Δημόσιας Σφαίρας* (public sphere sector → types) and *Τροπικότητα*
(modality → types, e.g. Πολυτροπικό → [Εικόνα, Γραπτό Κείμενο]).

### 2.4 Images (`extract_images`, `download_images`)
Only images inside the text section are kept. Logos and icons are filtered out, and so is anything
smaller than 80×80 px. Files are saved as `data/raw/images/trace_<doc:04>_<n:02>.<ext>`. The record
stores the path relative to `data/raw/` with forward slashes, so it works on any OS.

### 2.5 Checkpointing and export
* Each successful record is appended immediately to `trace_corpus.jsonl`. A re-run skips documents
  already there (same `SCHEMA_VERSION`), so an interrupted scrape just continues.
* Failures go to `errors.jsonl` with the reason, and the run continues.
* At the end: deduplicate by id → `trace_corpus.csv` (UTF-8 with BOM so Excel shows Greek) and
  `trace_corpus.parquet`. In these flat files, lists and dicts are stored as JSON strings.
* The scraper is polite: a 0.4 s delay between requests, retries with back-off on 429/5xx, and an
  identifying User-Agent.

## 3. Output schema (one record per text)

| Group | Fields |
|---|---|
| content | `document_id`, `title`, `text` |
| provenance | `trace_url`, `original_url`, `source`, `author_info`, `publication_date`, `language`, `word_count` |
| racism annotation | `racism_type`, `racism_categories`, `linguistic_means`, `racism_structure`, `broader_racism_subcategories` |
| context | `public_sphere_sector`, `public_sphere_types`, `text_genre`, `narrativity`, `humor` |
| modality | `modality`, `modality_types` |
| images | `image_urls`, `image_local_paths`, `image_alt_texts`, `image_titles`, `image_count` |

## 4. Full corpus (run of 2026-11-26)

| | |
|---|---|
| documents scraped | 785 / 830 |
| failed | 45, all "No text extracted": the wiki page has only the metadata table (the text lives in an external PDF/site, sometimes with an image). Mostly educational material, e.g. the *Δραστηριότητες βιωματικής μάθησης* series and language-teaching guides. Listed in `errors.jsonl`. |
| images | 974 (all downloaded); 229 texts have no image |
| racism type | 775 liquid racism, 10 *Αμιγώς Αντιρατσιστικό Κείμενο* (purely anti-racist, so no categories) |
| categories | Διάκριση 768, Αφομοίωση 364 |
| broader subcategories (texts) | παθητικός/η Άλλος/η 696 · απομακρυσμένος/η Άλλος/η 654 · Άλλος/η ως πρόβλημα 445 · ασθενής αφομοίωση 350 · ισχυρή αφομοίωση 137 |
| unmapped indicators | 0 |

## 4b. Earlier prototype subset (first 100 documents)

| | |
|---|---|
| documents scraped | 99 / 100 |
| failed | 1 (doc 40 *Oι μαθητές ερευνούν*: "No text extracted"; its text section has a different layout) |
| texts with images | 68 (111 images; one text has 13) |
| text length | 77 to 45,065 characters |
| racism type | all *Κείμενο Ρευστού Ρατσισμού* (liquid racism text) |
| categories | Διάκριση 99, Αφομοίωση 27 |
| most frequent indicators | inactive 'others' (69), anonymous 'others' (66), illegal/legal 'others' (50), 'others' as victims (45) |

> Note: the first 100 documents are alphabetical, not random. For the final evaluation, scrape the full
> corpus or sample at random so categories and sources stay balanced.
