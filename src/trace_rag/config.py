"""Central configuration: every path and tunable lives here.

Paths are resolved relative to the project root (the folder containing
``pyproject.toml``), so scripts behave the same no matter which directory
they are launched from.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

# ------------------------------------------------------------------
# Data layout (the whole data/ folder is git-ignored)
# ------------------------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data"

# Stage 1 output: the scraped corpus, exactly as it comes from the wiki.
RAW_DIR = DATA_DIR / "raw"
RAW_IMAGE_DIR = RAW_DIR / "images"
RAW_JSONL = RAW_DIR / "trace_corpus.jsonl"
RAW_CSV = RAW_DIR / "trace_corpus.csv"
RAW_PARQUET = RAW_DIR / "trace_corpus.parquet"
RAW_ERRORS = RAW_DIR / "errors.jsonl"

# Stage 2 output: cleaned documents, text chunks and image annotations.
PROCESSED_DIR = DATA_DIR / "processed"
DOCUMENTS_JSONL = PROCESSED_DIR / "documents.jsonl"
CHUNKS_JSONL = PROCESSED_DIR / "chunks.jsonl"
IMAGES_JSONL = PROCESSED_DIR / "images.jsonl"
IMAGE_ANNOTATION_CACHE = PROCESSED_DIR / "image_annotations_cache.jsonl"

# ------------------------------------------------------------------
# Stage 2: chunking
# ------------------------------------------------------------------

CHUNK_MAX_CHARS = 1000      # upper bound for one chunk
CHUNK_MIN_CHARS = 200       # a trailing chunk smaller than this is merged back
CHUNK_OVERLAP_CHARS = 150   # characters carried over from the previous chunk

# ------------------------------------------------------------------
# LLM / VLM access (OpenAI-compatible endpoint, OpenRouter by default)
# ------------------------------------------------------------------

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")
VLM_MODEL = os.getenv("VLM_MODEL", "google/gemini-2.5-flash")
