# Surprise-drop robustness

Offline probes used the real pipeline, disposable synthetic mirrors and SQLite, with models and transports disabled. Baseline stock was 60, inbound 45, demand 100 and median pack-out 100. A separate temporary copy of the team mirror confirmed the German PDF and corrupt PDF results, with forecasts and options unchanged.

Seven regressions run with `python -m unittest discover -s tests/drops -v`. Twenty probes run with `PYTHONPATH=. python tests/drops/audit_drops.py`. OCR results depend on local tools.

| Drop | Pipeline and dashboard result |
|---|---|
| German notice PDF | Extracted generic `what` only. ETA, forecast and options held steady without a warning. |
| German and Japanese MIME emails | Fixed 22 Nov (nick): `.eml` is now read as a notice. Headers and body are cited, the body goes through the notice parser, and attachments (PDF, scans, XLSX, DOCX, text; max 10, 20 MB each) are extracted with `file.eml#attachment` citations. Unsupported attachments raise a warning. The email still carries the review flag "verify email and any attachments". Fixture: `tests/drops/synthetic/hwaseong-delay.eml`. |
| Order confirmation PDF | Standard layout surfaced a cited PO discrepancy in truth. A date-first, re-columned acknowledgment extracted only the PO, with no parser error or warning. Both left shipment forecasts and options intact. |
| Reordered and renamed stock CSV | Known aliases, semicolon UTF-16 with DD.MM.YYYY and comma Windows-1252 with MM/DD/YYYY both parsed. Decimal-comma quantities summed to 81. Drop banner showed replacement. |
| UTF-16 and Windows-1252 PO CSV | Typed ingestion committed €2.40. Document reconciliation reopened the same file as UTF-8 and threw. The worker preserved the previous forecast and options and published `sync.error`. |
| Unknown required PO column | Rejected with the source and missing column in `sync.error`. Previous forecast and options remained available. |
| Ambiguous slash-date shipment | US-intended October 11 became November 10 on a canonical header. No warning. Both dates precede this fixture's shift, so its forecast and options were stable. |
| New stock date with two batches | Latest dated snapshot replaced the old date. On-hand fell to 30, median to 75 and an air-quote option appeared. |
| Shipment delayed, then cancelled | After-launch ETA cut median to 60 and created an air-quote option. Cancellation removed inbound and that option. |
| Cancellation disagrees with stale tracker | Truth raised a visible feed conflict and still counted all 45 units. Median stayed 100 and the option list stayed empty. |
| Shipment split | Distinct IDs and explicit quantities counted only the timely 20, giving median 80 and an air-quote option. Under one ID, the feeds were merged and both legs effectively missed launch. Median was 60 with an air-quote option. |
| Delivery-note JPEG | Upright OCR extracted the item and quantity. Rotation retained only the note identifier and an API review reason. The degraded scan generated OCR warning activity. No matching SAP receipt was supplied, so stock and options stayed stable. |
| Corrupt PDF | Published a document error and incremented the API error count. The drop looked successful and emitted no error activity. Forecast and options stayed stable. |
| Zero-byte / header-only stock CSV | Zero bytes raised a source-qualified sync error and preserved baseline. Header-only published as an empty snapshot, with median 45 and an air-quote option. That is unsafe if the export was truncated. |
| Corrupt workbook | Preserved baseline and options, with a per-source `sync.events` rejection on the first refresh. Neither UI consumes that field. |
| Same path changed / copied elsewhere | Same-path correction replaced rows and gave median 55 with an air-quote option. At a second path, the identical lot doubled on-hand to 120. A conflicting 10-unit copy yielded 70. The false stock totals left the median and option list unchanged in this fixture. |
| Removed from portal manifest | Removed shipment rows from truth even though the file stayed on disk. Median fell to 60 and the banner said removed. Local mode still scans retained bytes. |

Standalone renders `sync.error`. React currently omits it. Review reasons and extraction error counts are API fields. Only the degraded receipt emitted warning activity.

## Ranked fixes

1. Surface new source rejections and document review. Flag partial confirmations across filename conventions. Persist unresolved rejects across polls as a follow-up.
2. Keep authoritative ERP cancellations out of inbound while displaying the tracker conflict. Confirm the precedence rule with operations before rollout.
3. Share the CSV decoder. Later reuse header bindings and date rules while retaining original cell quotes.
4. Require locale, leg IDs, snapshot identity and completeness. Route unsupported email, unparsed notices and uncertain OCR to review.

## What to tell judges

Show a late shipment, complete stock snapshot or explicit split recalculating forecast and options. Unfamiliar PDFs and emails may require operator review. A success banner confirms a file change and can coexist with missing facts or stale forecasts.

## Proposed diff for codex-truth

Tested in an isolated source copy. The Python probes recovered both encodings, excluded the cancelled shipment, surfaced the workbook rejection and flagged the re-columned confirmation. The patched React build passed. Browser rendering was not exercised.

```diff
--- a/src/orchestrator/__main__.py
+++ b/src/orchestrator/__main__.py
@@ -71,4 +71,13 @@
     traced = []
+    review = []
     pages = {}
     for doc in documents(con):
+        problem = doc.get("error") or ", ".join(doc.get("review_reasons", []))
+        if problem:
+            review.append({
+                "id": f'doc:{doc["source"]}:review', "agent": "Document Agent",
+                "tool": "document_review", "type": "warning", "status": "error",
+                "action": problem, "input_ref": doc["source"], "output_ref": None,
+                "citation": {"file": doc["source"]}, "time": "",
+            })
         for index, event in enumerate(doc.get("activity", [])):
@@ -103,3 +112,3 @@
     shown = {event["id"] for event in proof}
-    recent = [*escalation, *proof, *general, *sorted((event for event in traced if event["id"] not in shown),
+    recent = [*escalation, *proof, *review[-5:], *general, *sorted((event for event in traced if event["id"] not in shown),
                                                   key=lambda event: event["time"], reverse=True)]
@@ -267,2 +276,6 @@
             chaser.expire(con)
+            rejected = [event for event in events if event["action"] == "error"]
+            if rejected:
+                summary = "Source rejected: " + ", ".join(event["source"] for event in rejected)
+                sync_error = f"{sync_error} {summary}" if sync_error else summary
             with con:
--- a/web/src/api.ts
+++ b/web/src/api.ts
@@ -93,3 +93,3 @@
   drop: { title: string; detail: string; time: string } | null;
-  sync?: { pendingDrop?: number; lastSync?: string; detail?: string; mode?: string };
+  sync?: { error?: string | null; pendingDrop?: number; lastSync?: string; detail?: string; mode?: string };
   model?: string;
--- a/web/src/main.tsx
+++ b/web/src/main.tsx
@@ -202,2 +202,3 @@

+      {data.sync?.error && <div className="error-banner" role="alert">{data.sync.error}</div>}
       {error && <div className="error-banner">{error}<button onClick={() => setError("")}>×</button></div>}
--- a/src/docs/pipeline.py
+++ b/src/docs/pipeline.py
@@ -166,2 +166,6 @@
                 row["review_reasons"] = []
+                if row["kind"] == "confirmation" and not (
+                    {"items", "shipped", "balance", "dock_hold"} & row["fields"].keys()
+                ):
+                    row["review_reasons"].append("unparsed_confirmation")
                 if row["kind"] == "receiving":
--- a/src/docs/reconcile.py
+++ b/src/docs/reconcile.py
@@ -3,4 +3,7 @@
 import csv
+import io
 import re
 from collections import defaultdict
+
+from src.ingest.readers import decode_csv

@@ -35,3 +38,3 @@
             continue
-        with path.open(encoding="utf-8-sig", newline="") as stream:
+        with io.StringIO(decode_csv(path.read_bytes()), newline="") as stream:
             sample = stream.readline()
--- a/src/truth/__init__.py
+++ b/src/truth/__init__.py
@@ -388,3 +388,4 @@
         statuses = {row["status"] for row in feeds if row["status"]}
-        if statuses and statuses <= CANCELLED or head.get("status") in {"delivered", "received"}:
+        authoritative_cancel = "erp/" in head["source"]["file"] and head.get("status") in CANCELLED
+        if authoritative_cancel or (statuses and statuses <= CANCELLED) or head.get("status") in {"delivered", "received"}:
             continue
```
