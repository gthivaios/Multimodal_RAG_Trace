# TRACE Multimodal RAG

**Evidence-grounded discourse analysis on the TRACE anti-racist corpus.**

[TRACE](https://trace.library.upatras.gr) is a corpus of 830 Greek anti-racist texts (2015–2020, 41
sources, ~500k words) annotated for **liquid racism**: texts where anti-racist and exclusionary
representations coexist. This project builds a multimodal Retrieval-Augmented Generation (RAG) system
on top of it. Given a research question or an unseen excerpt, it retrieves relevant theory, annotated
examples and corpus evidence (text **and** images). It then explains *which* discrimination pattern is
present and *why*, citing every source.

Project proposal: [`docs/proposal/`](docs/proposal/) · Full plan: [`docs/00_roadmap.md`](docs/00_roadmap.md)

## Stages

| # | Stage | Status | Documentation |
|---|-------|--------|---------------|
| 1 | Corpus acquisition (texts, metadata, images) | ✅ | [docs/01_corpus_acquisition.md](docs/01_corpus_acquisition.md) |
| 2 | Multimodal preprocessing (cleaning, chunking, image OCR/description) | ✅ | [docs/02_preprocessing.md](docs/02_preprocessing.md) |
| 3 | Reference knowledge base | ⏳ | |
| 4 | Indexing & retrieval | ⏳ | |
| 5 | Grounded generation | ⏳ | |
| 6 | Test set & evaluation | ⏳ | |
| 7 | Interface | ⏳ | |

## Repository layout

```
├── docs/                  one document per stage + the proposal deck
├── scripts/               one entry script per stage (01_…, 02_…)
├── src/trace_rag/         the Python package
│   ├── config.py          all paths and parameters
│   ├── scraping/          Stage 1
│   └── preprocessing/     Stage 2
├── tests/
├── data/                  (git-ignored) raw/ and processed/ outputs
├── .env.example           template for the API key
└── pyproject.toml / requirements.txt
```

## Setup (Windows PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .                 # makes `trace_rag` importable from scripts and notebooks
copy .env.example .env           # then add your OPENROUTER_API_KEY
```

## Run

```powershell
python scripts/01_scrape_corpus.py --limit 100   # Stage 1: scrape the first 100 texts
python scripts/02_preprocess.py                  # Stage 2: chunks + image annotation
pytest                                           # unit tests
```

## Data and licensing

The scraped texts and images belong to their original publishers and to the TRACE project. They are
**not** included in this repository (`data/` is git-ignored). Run Stage 1 to rebuild them locally.
