from trace_rag.preprocessing.chunking import split_text
from trace_rag.preprocessing.documents import normalize_text
from trace_rag.scraping.trace_scraper import build_trace_url, parse_integer


def test_greek_question_mark_is_encoded():
    assert build_trace_url("Έχεις αναπτήρα;").endswith("%3B")


def test_parse_integer():
    assert parse_integer("1.234 λέξεις") == 1234
    assert parse_integer(None) is None


def test_mixed_script_is_fixed():
    # Latin "O" followed by Greek "ι"
    assert normalize_text("Oι μαθητές") == "Οι μαθητές"
    # pure Latin words are untouched
    assert normalize_text("COVID και UNHCR") == "COVID και UNHCR"


def test_short_text_is_one_chunk():
    assert split_text("Μικρό κείμενο.", max_chars=100) == ["Μικρό κείμενο."]


def test_chunks_respect_max_length():
    paragraph = "Αυτή είναι μια πρόταση για δοκιμή. " * 20
    text = "\n\n".join([paragraph.strip()] * 5)
    chunks = split_text(text, max_chars=300, min_chars=50, overlap_chars=50)
    assert len(chunks) > 1
    # +min_chars: the last chunk may absorb a small tail
    assert all(len(c) <= 300 + 50 for c in chunks)
