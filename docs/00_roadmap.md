# Roadmap: Multimodal RAG for TRACE

This project implements the proposal in
[`docs/proposal/Proposal_Draft_TRACE_NLTP_detailed.pptx`](proposal/Proposal_Draft_TRACE_NLTP_detailed.pptx):
a RAG system that is used as an **analytical layer** over the TRACE corpus. The system does more than
classify a text. It retrieves evidence and explains *why* an excerpt relates to a discrimination type,
grounded in the TRACE theoretical framework.

> **Research question.** Can retrieved TRACE evidence and theoretical knowledge support accurate,
> explainable and theoretically consistent interpretations?

## Conceptual workflow (from the proposal)

```
 1. TRACE wiki corpus   ──►  2. Multimodal          ──►  3. Information    ──►  4. LLM response
    texts, images,            preprocessing              retrieval              grounded answer
    metadata, annotations     chunks + image text        evidence + theory      + explanation
                                                          ▲
                              Reference knowledge base ───┘
                              (definitions, mechanisms, annotated examples)
```

## Stages

| # | Stage | Status | Code | Doc |
|---|-------|--------|------|-----|
| 0 | Project setup (clean repo, config, packaging) | ✅ done | `pyproject.toml`, `src/trace_rag/config.py` | [README](../README.md) |
| 1 | Corpus acquisition: scrape texts, metadata, images | ✅ done | `src/trace_rag/scraping/` | [01](01_corpus_acquisition.md) |
| 2 | Multimodal preprocessing: clean docs, chunk text, VLM OCR + image descriptions | ✅ code done (VLM run pending) | `src/trace_rag/preprocessing/` | [02](02_preprocessing.md) |
| 3 | Reference knowledge base: one record per TRACE category | ⏳ next | `knowledge_base/` | 03 |
| 4 | Indexing & retrieval: hybrid text search, image search, KB search | ⏳ | `src/trace_rag/retrieval/` | 04 |
| 5 | Grounded generation: category + explanation + citations | ⏳ | `src/trace_rag/generation/` | 05 |
| 6 | Human-reference test set & evaluation (retrieval + response, ablations) | ⏳ | `src/trace_rag/evaluation/` | 06 |
| 7 | Interface: Gradio app for corpus exploration | ⏳ | `app/` | 07 |

## Planned design of the upcoming stages

### Stage 3: Reference knowledge base
One structured YAML record per TRACE category, as on slide 6 of the proposal:

| Field | Content |
|---|---|
| `theoretical_definition` | what the category means (liquid racism framework) |
| `research_question` | what the category examines |
| `linguistic_mechanisms` | observable indicators: the exact "linguistic means" labels from the wiki |
| `annotated_examples` | 3 excerpts with expert explanations |

The scraped metadata has only **two** top-level categories (Διάκριση, Αφομοίωση) and 11 linguistic
indicators. The subcategories on slide 2 (*the Other as a problem*, *the distant Other*,
*the passive Other*, *weak / strong assimilation*) are **not** in the page metadata. Stage 3 maps
indicators to subcategories. That mapping must be confirmed by a domain expert.

The **held-out test split** (Stage 6) is fixed here too, so test documents are never used as KB examples
or indexed as evidence.

### Stage 4: Indexing & retrieval
* **Text:** multilingual dense embeddings (e.g. `intfloat/multilingual-e5-base`, which supports Greek)
  plus BM25, fused with reciprocal-rank fusion. The index holds text chunks **and** image
  `retrieval_text` (description + OCR), so images are found by what they show.
* **Images (visual):** optional multilingual CLIP embeddings for image-to-image similarity.
* **Knowledge base:** a separate small index, so every answer can retrieve theory, not only passages.
* Vector store: Chroma (local, persistent).

### Stage 5: Grounded generation
The prompt receives (a) the retrieved KB records, (b) the retrieved evidence chunks/images with ids.
The output is structured JSON: `category`, `linguistic_mechanisms`, `evidence_spans`, `explanation`,
`citations`. Each claim must cite a chunk or KB id, which makes the answer *traceable and auditable*.

### Stage 6: Evaluation
* **Test set:** held-out, expert-annotated cases: input excerpt + research question, gold category,
  expected evidence (mechanisms + spans), reference explanation.
* **Retrieval:** Recall@k / MRR. Did it retrieve the right theory and evidence?
* **Response:** category accuracy / F1, mechanism F1, groundedness and explanation quality
  (LLM-as-judge, checked against expert ratings on a sample).
* **Ablations (slide 8):** LLM-only vs. indicator prompting vs. full RAG; text-only vs. multimodal.
