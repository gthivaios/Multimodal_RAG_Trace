"""Stage 1 - scrape the TRACE wiki into data/raw/.

Examples:
    python scripts/01_scrape_corpus.py --limit 100     # first 100 texts (prototype)
    python scripts/01_scrape_corpus.py                 # full corpus (~830 texts)
    python scripts/01_scrape_corpus.py --no-images     # text + metadata only
"""

import argparse

from trace_rag.scraping.trace_scraper import run

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--limit", type=int, default=None, help="scrape only the first N documents")
parser.add_argument("--no-images", action="store_true", help="do not download images")
args = parser.parse_args()

run(limit=args.limit, download_images_flag=not args.no_images)
