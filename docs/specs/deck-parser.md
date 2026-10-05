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
- Unpack cap (.pptx, .docx are zip files): reject a file that unpacks to more than 250 MB or
  holds more than 5,000 parts, with a clear message, before it is opened.
- pdf: characters are read in the order the file writes them, so a number stays whole
  (axis labels 500, 600 are not split into single digits).
- Layout kept for section 2: each line keeps its text box (pptx, docx text boxes; a stack of
  lines in a pdf), its position on the slide or page (pptx, pdf) and whether it is the slide
  title (pptx) or the topmost text of the page (pdf).

## 2. Candidate claim detection (Python only, no LLM, rule-based)
Only plan claims are listed: the company's own revenue, customers, users, retention, margins,
gross profit, costs, EBITDA, net profit, sales metrics, hiring and launch dates, plus targets and forecasts.
A figure (a number, or a date) is a candidate if it has a claim keyword: in its own text line,
or borrowed from nearby text when its line has none.
Keywords and claim types (a keyword also matches its plural and verb forms: revenues, growing,
hired, launches; of two overlapping keywords the longer one counts):
- Revenue: ARR, MRR, revenue, bookings, turnover
- Growth: growth, grow, CAGR. A growth word gives a rate (% or x) its type from the noun on the
  same line: revenue → Revenue growth, users → User growth, otherwise Growth; never Revenue by
  default. An amount or a count beside a growth word takes the noun's own type ("ARR grew to
  $3.6M" is Revenue).
- Retention: NRR, churn, retention, customer life
- Sales: sales cycle, win rate, pipeline, ACV, CAC, payback, LTV, (customer) lifetime value,
  acquisition, conversion, leads, cost of (paid) acquisition, acquisition cost
- Customers: customers, clients, paying users, accounts, companies, agencies, subscribers,
  institutions
- Users: users
- Gross margin: margin, margins
- Gross profit: gross profit; also a gross margin given as an amount ("Gross margin £1.2M")
- Costs: direct costs, costs, opex
- EBITDA: EBITDA, profitability, profitable, break-even
- Net profit: net profit, net income, net loss. A net loss is stored as a negative net profit
  ("Net loss of $2M" → -2,000,000).
- People: hires, headcount, team, recruitment, attrition
- Product: launch, release, roadmap, ship, milestone, Q1–Q4, month names
- Market: TAM, SAM, SOM, addressable market, market size. The bare word "market" does not count.
The unit of a count is the noun it counts: "800 paying users". If a Customers or Users keyword
appears within the next 4 words after the number, it is the unit (">50 Dutch temporary work
agencies" → agencies); otherwise the word right after the number. The search stops at the next
figure: a keyword after it belongs to that figure ("5 advisors & 15 clients" → 5 advisors).
There is no Usage type: a count whose line has no keyword borrows a label like any other
figure, or is not a candidate.
A line with its own keyword never borrows a label from other lines.
Periods are dates, never values: "Y/E 22", "22 Y/E", "FY23", "2023E" (also A, F, B, P),
"H1 24", "1H24", "Q3 25", "3Q25". A half year is stored as "2024-H1".
Borrowing: a figure without a keyword or a date in its own line takes them from nearby text,
first match wins: the table column header, the other lines of its text box (nearest first),
the text on the same row or above it, never below, within a quarter of the slide or page
(nearest first), the slide title. A month or quarter is preferred over a bare year.
A date is taken first from the figure's column header, then from a period line at the top of
its text box ("23 Y/E" over "Gross Profit £150K" and "5K Users"), then as above. The box period
dates figures only; the period line itself is never a candidate.
The snippet is the figure's own line. A borrowed label is kept apart and shown below the
snippet as "Label from: <text>"; a borrowed date as "Date from: <text>".
A line with no figure becomes a candidate only if it is a product line (launch, release, ship,
roadmap or milestone, its own or borrowed) or an EBITDA line ("Positive EBITDA") and it can
borrow a date: a roadmap bullet, a break-even milestone. A bare date under an EBITDA line
("Q2 2024") takes the EBITDA type.
Tables: one candidate per table row. The row's figures of one type become a single candidate
that holds its values by period, each with the date and the text of its column header
("Registered Users: 200 (Y/E 22) · 5,000 (Y/E 23) · …"). A lone figure, or figures of different
types in one row, stay separate candidates. A header row of periods is never a candidate.
Each candidate stores: claim type, value (low and high for a range), unit, currency, target
date (if any), source reference, short snippet (max 300 characters), and the text a label or
date was borrowed from. A table row stores its values by period instead of one value and date:
value (low and high), target date, the column header text and the cell of each.
Duplicates across slides are merged and keep all source references.
Dropped, never listed:
- Chart axis ticks: 3 or more numbers, evenly spaced in value, in one line, in one column or
  row of lines that hold only a number, or in one table column (row numbers 1, 2, 3). A table
  row is a series of values and the header row holds labels: neither is ever ticks.
- Every figure on a slide or page titled Problem, Why now, Trends, Landscape, Background,
  Token or Allocation (pptx titles and the topmost text of a pdf page; docx has no titles).
- Every figure on a slide or page that cites outside research: a "Source:" or "Via <link>"
  line, or two or more footnote lines ("1. …", a bare link).
- Figures in a line about funds raised (raise, funding, investment, investors, valuation, seed
  round, Series A–D), tokens (token, allocation, vesting, total supply, lockup), people's careers
  (founder, CEO, chief, former, previously, employee, exec team) or the industry and the world
  (industry, global, worldwide, economy). This also drops other companies' figures quoted in
  founder bios.
Deck inconsistency: when one deck gives the same type and period different values (the page 19
panel's Gross Profit £150K for Y/E 23, the table's £ 50,000), every candidate holding one of them
is marked "Deck inconsistency" with that period. Only stated periods are compared: the figure's
own date, its column header's or its box's period. A date borrowed by position or from the
title is not, and neither are amounts in different currencies, or a rate and an amount. The
mark describes the deck and is set when it is read; an edit does not clear it.
Tried and rejected: a bare number (no words of its own) borrowing only from its own text box,
table header or a label right next to it. On the test set it lowered recall to 93.2% when
first tried and to 90.3% on top of the other plan-claim rules (chart data labels whose only
label is the chart's axis title, among others), below the 95% mark. Bare numbers still borrow
by position and from the slide title.

## 3. Recall test
- Test set: 10 public decks (6 pdf, 2 pptx, 2 docx) in tests/fixtures/decks/decks/.
- A hand-checked answer file lists the claims in each deck, one entry per value. A table row
  candidate is matched value by value, so recall stays per value; it counts once as a candidate.
- Pass mark: the parser finds at least 95% of listed claims.
- Precision (false candidates) is reported; the test fails if it drops below 30%.
- Runs as a normal automated test.

## 4. What may reach the model
- The deck parser has no import of, or call to, the LLM gateway.
- Two paths reach the gateway, and each has its own fields:
  a) Narrative path: computed results from MongoDB and the structured claim fields (type, value, high value of a range, unit, date, status).
  b) Structure path (rule 16): redacted deck structures and spreadsheet header rows with, per column, either up to 3 sample values (numeric and date columns only) or a profile (distinct count, typical length, shape pattern) for text columns, as extracted text with cell positions, only with per-audit consent. Table cells, including a row's values by period, travel this path and no other.
- An automated test fails the build if the parser imports the gateway, if the gateway reads parsed-text, snippet or source-reference fields, or if the structure path sends anything other than redacted structure text and spreadsheet headers with their samples or profiles. The narrative path is unchanged.
- Logs and MongoDB store model JSON output (values with cell references), prompt version, model version, content hash, token counts and cost. Never deck text sent to the model. Delete audit removes model outputs.
- Model output never becomes Verified on its own. Python must match every value to a source cell. Unmatched values are shown as 'AI suggestion, not verified' or dropped.

## 5. Storage and deletion
- Parsed text and candidates are stored in MongoDB, linked to the audit. An audit can hold
  several decks (needed later for the forecast track record).
- The "delete audit" button also removes parsed text and candidates.
- A "Remove deck" button per deck, after the confirm step "This deletes the deck and all its
  claims, including reviewed ones.", deletes that deck's parsed text and all its candidates,
  reviewed ones included (DELETE /api/audits/{id}/decks/{deck_id}).

## 6. Approval
Shown above the approval list, word for word:
"Claims found in the deck
These figures may inform the growth plan. They were identified automatically and may contain errors. Check each claim against its source slide, then choose:
✓ Approve: Confirm this is a claim the company makes. It will be added to the claim register and tested against the data.
✎ Edit: Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data.
✕ Reject: Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used."
- Approve: status "approved".
- Edit: corrects type, value (low and high), unit, currency or date and approves the claim:
  status "edited", the parser's original values kept next to the edit. Approving an edited
  claim keeps it "edited". The snippet, borrowed label and sources cannot be edited.
- A table row is approved, edited or rejected once. Editing it corrects one or more of its
  values by period; the periods and cells stay.
- A claim marked "Deck inconsistency" shows the label in its status cell.
- Reject: status "rejected". The record is kept, never deleted; it is not in the register.
- Claim register: the approved and edited claims of an audit (GET /api/audits/{id}/claims).
- Not built yet: testing register claims against the uploaded data. It needs its own spec.
- Uploading the same file again replaces its parsed text and its unreviewed candidates only;
  approved, edited and rejected claims stay, and the same claim is not added twice.
- Every column of the approval list has a header; the value shows its unit or currency.
- A deck selector sits above the claims table: one tab per deck, plus "All". Each tab shows the
  deck name and its claim count. It opens on the most recently uploaded deck.
- Within a deck, claims to review come first, then the rest, each by slide or page. The order
  is set when the list loads, so a row does not move while it is being reviewed.

## 7. Structure detection (Python only, no LLM)
Finds the structures that CLAUDE.md rule 16 lets the gateway read (docs/specs/llm-structure-reading.md). Every structure
keeps its source reference (file, slide or page) and every cell keeps its row and column, so a value read from it can be
cited. Structures are stored with the deck's parsed text and deleted with it (§5).
- Tables and text boxes: read as today (§1).
- Charts (pptx): read from the chart XML: series, data labels, chart title and axis titles.
- KPI panels: text boxes with a number beside a short label.
- Roadmaps and timelines: text boxes with dates.
- Hiring, unit-economics and use-of-funds tables: tables classified by header keywords. Any other table is a table.
- Text that is none of these is prose and is never a structure.
Python assigns the type. The model may confirm or correct it in its type field, and Python logs any change.
The keyword lists, the label length and how many dates make a timeline are fixed on the 10 test decks at build time
and written into this section.

## Done when
- All three formats parse with correct slide/page references.
- Recall test passes at 95%+ with precision at 30%+.
- Isolation test passes.
- Approval list in the frontend shows candidates with their source reference.
- Upload screen shows the scope message.
