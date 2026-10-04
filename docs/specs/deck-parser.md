# Spec: Deck parser and candidate claim detection
Status: Approved
Location: docs/specs/deck-parser.md

## Goal
Read a board deck or growth plan and list candidate claims for the analyst to approve.
The analyst types nothing. They only approve, reject or edit each candidate.

## Scope
In: .pptx, .pdf (text-based), .docx.
Out: scanned PDFs, images inside slides, charts saved as pictures, .key files, Google Slides links.

Message shown to the user on the upload screen:
"We read text from PowerPoint, Word and text-based PDF files.
We cannot read:
- Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.
- Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.
If a number you need sits in a picture, add it as text or send the source spreadsheet."

If a file has no readable text, show: "No readable text found in this file. It may be scanned or made of images. Please upload a text-based version." Do not guess.

## 1. Parsing
- Libraries: python-pptx, pdfplumber, python-docx.
- Every text block keeps its reference: file name + slide number (pptx), page number (pdf, docx).
- pptx: read text boxes, tables and speaker notes. Mark notes as "notes".
- Tables: keep row and column so the source can be cited.
- Limits: max 50 MB per file, max 200 slides/pages. Reject larger files with a clear message.

## 2. Candidate claim detection (Python only, no LLM)
A text line is a candidate if it holds a number AND a claim keyword:
- Growth and revenue: ARR, MRR, revenue, growth, CAGR, bookings
- Retention: NRR, churn, retention
- Sales: sales cycle, win rate, pipeline, ACV, CAC, payback
- People: hires, headcount, team
- Product: launch, release, roadmap, Q1–Q4, month names
- Market: TAM, SAM, SOM, market size
Each candidate stores: claim type, value, unit, currency, target date (if any), source reference, short snippet (max 300 characters).
Duplicates across slides are merged and keep all source references.

## 3. Recall test
- Test set: 10 public decks (6 pdf, 2 pptx, 2 docx) in tests/fixtures/decks/decks/.
- A hand-checked answer file lists the claims in each deck.
- Pass mark: the parser finds at least 90% of listed claims.
- Precision (false candidates) is reported but does not fail the test.
- Runs as a normal automated test.

## 4. No deck text reaching the model
- The deck parser has no import of, or call to, the LLM gateway.
- The gateway never reads raw files, parsed text or claim snippets.
- The gateway may read only structured claim fields (type, value, unit, date, status).
- An automated test fails the build if the parser imports the gateway, or the gateway reads the parsed-text or snippet fields.

## 5. Storage and deletion
- Parsed text and candidates are stored in MongoDB, linked to the audit.
- The "delete audit" button also removes parsed text and candidates.

## Done when
- All three formats parse with correct slide/page references.
- Recall test passes at 90%+.
- Isolation test passes.
- Approval list in the frontend shows candidates with their source reference.
- Upload screen shows the scope message.
