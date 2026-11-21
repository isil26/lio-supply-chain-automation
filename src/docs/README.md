# T2 document extraction

From the repository root, use a Python environment with the project requirements and Pillow. Pillow enables local handwriting crops and the PDF raster fallback.

```sh
python3 -m pip install -r requirements.txt Pillow
python3 -m src.docs.run
python3 -m unittest src.docs.test_docs
```

The CLI reads the synced data mirror and publishes `store/docs.jsonl`. It reports document, cache-hit, mismatch, review, warning and error counts. For a separate mirror or output location, pass `--data`, `--state` and `--output`. Automatic portal refresh belongs to the bridge.

## Input formats

- Order confirmations use text from Ghostscript's `txtwrite` or pypdf. The parser reads aligned and stacked item layouts, normalizes SAP item numbers, and preserves commercial conditions. Shipping advices and packing lists in the same folder use their own fields within the confirmation category.
- Contracts and notices expose cited clauses, part annexes, supplier material aliases, effective dates, downtime and capacity where the source provides them. XLSX price lists use named columns, with citations to the worksheet and row.
- Receiving images support a vision-language model and local OCR. The pipeline preserves printed and handwritten quantities. A supported handwritten correction supplies the effective item quantity. Uncorroborated crop readings remain visible as `handwriting_candidate` for review.
- Scanned pages use local Ghostscript rendering or pypdfium2. Install Tesseract with English, Polish, Korean and Simplified Chinese language data for offline scans. On macOS the pipeline can also use a working Apple Vision helper or compile `ocr.swift` with `swiftc` when available.

## Model providers

Set `SOONY_VISION_MODEL` to an image-capable model served by a local OpenAI-compatible chat endpoint. Set `SOONY_LOCAL_MODEL` to a local text model to add English translations and structured facts for Korean, Chinese, Polish and English documents. The endpoint defaults to Ollama at `http://127.0.0.1:11434/v1/chat/completions`. Set `SOONY_LOCAL_URL` for another loopback endpoint. Source text and images stay local with these adapters.

Call `run_pipeline(data, state, output, vision=..., translator=...)` from `src.docs.pipeline` to use other provider implementations. The `VisionClient.extract(image, *, kind)` method returns optional page `text` and a `facts` object. `TranslationClient.extract(text, *, kind)` returns a `facts` object directly. Each facts object maps field names to lists of `{value, quote, confidence}`. Providers supply original-language quotes. The pipeline binds those quotes to the page and source path and verifies text translations against the transcription. Implement `cache_key` on each provider and change it when its extraction behavior changes.

The local OCR path works independently of model configuration. Its handwriting fallback searches below the printed quantity cell, reads the crop at multiple thresholds, and checks whether the PO quantity and SAP receipt independently corroborate the candidate and printed value. Other handwritten corrections should be checked with the vision provider or on the original scan.

## Output contract

Each JSONL row represents one source and carries `source`, `sha`, `kind`, `supplier_id`, `pages`, `methods`, `warnings`, `error`, `fields`, `mismatches` and `review_reasons`. Paths are relative to the data root. A field name maps to a list of evidence records.

```json
{
  "value": "PLN",
  "source_file": "suppliers/SUP-0001_Test/notices/price_list.xlsx",
  "page": 1,
  "quote": "CMP-TST-001 | 1.20 | 1.24 | PLN",
  "confidence": 1.0,
  "sheet": "Prices",
  "row": 2
}
```

PDF and image pages are 1-based. XLSX uses the 1-based sheet index as `page` and includes the sheet title and Excel row. ERP fields use `page: null` with CSV row and column. Item records cite the source row that supports their values. When a correction comes from a separate crop, the item also carries the printed evidence and any independent corroboration.

Comparison records include the code, field, optional PO line, and document and ERP evidence. A delivery below the PO total is recorded as `partial_delivery`. A different quantity booked against the same delivery note and item is a `goods_receipt_mismatch`. Supplier material aliases come from extracted cross-reference tables.

Extraction is cached in `store/docs_cache.sqlite3` by verified content SHA-256, parser revision and provider configuration. When present, the bridge manifest selects active sources and supplies the SHA-256 to check against the local bytes. Without a manifest, the CLI discovers sources in the mirror. ERP comparisons are refreshed on every run, including when document extraction hits the cache. Re-running replaces the snapshot atomically, removes deleted sources, and retries failed readings. A nonzero CLI exit means the published snapshot includes documents with extraction errors.

## SQLite and orchestration

```sh
python3 -m src.docs.run --sqlite store/soony.db
```

Or pass an existing SQLite connection to `src.docs.load_table(connection, path)`. The loader replaces the T2-owned `doc_extractions` table and retains the full JSON in `payload`. `src.docs.documents(connection)` yields legacy-compatible `fields` with the `citation.file` alias. `src.docs.extract(connection, data_root)` runs the pipeline and loads the table in one call for T7.
