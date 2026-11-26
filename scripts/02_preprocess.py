"""Stage 2 - multimodal preprocessing: data/raw/ -> data/processed/.

Examples:
    python scripts/02_preprocess.py                # chunk texts + annotate images with the VLM
    python scripts/02_preprocess.py --no-vlm       # chunk texts only (free, offline)
"""

import argparse

from trace_rag.preprocessing.pipeline import run

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--no-vlm", action="store_true", help="skip image OCR/description (no API calls)")
args = parser.parse_args()

run(annotate_images=not args.no_vlm)
