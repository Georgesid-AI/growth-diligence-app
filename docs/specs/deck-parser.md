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
gross profit, costs, EBITDA, net profit, sales metrics, unit economics (LTV, CAC, LTV/CAC, customer lifetime), cash,
burn, runway, free trials per day, months to profitability, hiring and launch dates, plus targets and forecasts.
A figure (a number, or a date) is a candidate if it has a claim keyword: in its own text line,
or borrowed from nearby text when its line has none.
Keywords and claim types (a keyword also matches its plural and verb forms: revenues, growing,
hired, launches; of two overlapping keywords the longer one counts):
- Revenue: ARR, MRR, revenue, bookings, turnover
- Growth: growth, grow, CAGR. A growth word gives a rate (% or x) its type from the noun on the
  same line: revenue → Revenue growth, users → User growth, otherwise Growth; never Revenue by
  default. An amount or a count beside a growth word takes the noun's own type ("ARR grew to
  $3.6M" is Revenue).
- Retention: NRR, churn, retention
- Sales: sales cycle, win rate, pipeline, ACV, payback, acquisition, conversion, leads
- Customers: customers, clients, paying users, accounts, companies, agencies, subscribers,
  institutions
- Users: users
- Gross margin: margin, margins
- Gross profit: gross profit; also a gross margin given as an amount ("Gross margin £1.2M")
- Costs: direct costs, costs, opex
- EBITDA: EBITDA, profitability, profitable, break-even. "Profitable" with a figure in months is months to
  profitability (below).
- Net profit: net profit, net income, net loss. A net loss is stored as a negative net profit
  ("Net loss of $2M" → -2,000,000).
- People: hires, headcount, team, recruitment, attrition
- Product: launch, release, roadmap, ship, milestone, Q1–Q4, month names
- Market: TAM, SAM, SOM, addressable market, market size. The bare word "market" does not count.
- Claim types of issue #45 (decisions of 2026-10-06). The keywords of LTV, CAC and customer life move here from
  Sales and Retention, and "profitable" with a figure in months from EBITDA:
  - LTV: LTV, (customer) lifetime value (a lifetime value, in a currency)
  - CAC: CAC, cost of (paid) acquisition, acquisition cost (in a currency)
  - LTV/CAC: LTV/CAC, also written "LTV / CAC", "LTV:CAC" or "LTV to CAC" (unit x). It is longer than LTV and CAC,
    so it counts over both.
  - Customer lifetime: customer life, customer lifetime (unit months). "Customer lifetime value" is LTV, the
    longer keyword.
  - Months to profitability: "profitable" whose figure is a number of months ("Profitable in 10 months"). Any
    other "profitable" figure or line stays EBITDA: a dated one is an EBITDA milestone ("By December, moz is
    profitable"; decision of 2026-10-06, so it matches the roadmap category `break_even`, structure-labelling.md §2).
  - Cash: cash, the cash balance ("Cash on hand" / "$7m left", in a currency). "Cash flow" does not count.
  - Burn: burn, net burn, burn rate (in a currency)
  - Runway: runway (unit months)
  - Trials per day: trials per day, trials / day ("# of New Free Trials / Day", a count)
  On the 10 test decks these change 11 candidates' type and no other candidate (no row appears or disappears):
  front-b p12 "LTV / CAC" 2.5, 2.6, 4.4 (Sales → LTV/CAC); front-b p15 "$7m left" (Revenue → Cash), "18 months"
  (EBITDA → Runway), "Profitable in 10 months" (EBITDA → Months to profitability); moz p20 "~$900" (Sales → LTV),
  "~$100" (Sales → CAC), "~9 Months"
  (Retention → Customer lifetime), "~100" (Customers → Trials per day); buffer p7 "LTV of $240" (Sales → LTV).
  Three of them also borrow their label from the right box: "$7m left" from "Cash on hand" (was "Seed to Series
  A …"), "18 months" from "Runway *" (was "“Default alive” † Profitable in 10 months") and moz p20 "~100" from "# of
  New Free Trials / Day" (was "Number of PRO Subscribers"). 236 candidates before and after.
The unit of a count is the noun it counts: "800 paying users". If a Customers or Users keyword
appears within the next 4 words after the number, it is the unit (">50 Dutch temporary work
agencies" → agencies); otherwise the word right after the number. The search stops at the next
figure: a keyword after it belongs to that figure ("5 advisors & 15 clients" → 5 advisors).
There is no Usage type: a count whose line has no keyword borrows a label like any other
figure, or is not a candidate.
A line with its own keyword never borrows a label from other lines.
Periods are dates, never values: "Y/E 22", "22 Y/E", "FY23", "2023E" (also A, F, B, P),
"H1 24", "1H24", "Q3 25", "3Q25". A half year is stored as "2024-H1".
Period rules (apply to tables, structure text and the verifier):
- Header stack: extracted structure text includes every header row above the data; a merged range is written with its span, e.g. "FY2025 (r1c3:r1c14)". The model receives the full header stack, not only the row directly above the values. On the column-mapping path the stack is capped at 3 header rows, the 3 nearest the data, and carries no text cell values.
- A period may be built from two cells: the month or quarter cell and the year cell above it in the same column range. "Mar" + "2025" → 2025-03; "Q3" + "2025" → 2025-Q3. With a year-end other than December, a month under any year header (plain or FY) is shifted by the year-end: months after the year-end month belong to the previous calendar year, months up to and including it to the named year (March year-end: "Apr" + "FY2025" → 2024-04, "Mar" + "FY2025" → 2025-03).
- Month names are matched in English, German and Bulgarian, short and long forms, any case.
- A month or quarter header with no year cell above it in the same column range → period null. Never infer the year from the deck date, the file name or neighbouring columns.
- `fiscal_year_end` is a month field on the audit creation screen, default December, and stays editable after creation through PUT /audits/{id} in the existing MappingWizard settings (no new screen). Changing it re-runs period mapping.
- Fiscal years are named by the calendar year in which they end: with a March year-end, FY25 = 2024-04-01 to 2025-03-31; with December, FY25 = 2025. With a year-end other than December, every year, quarter and half label is fiscal ("2025E", "Q1 25", "H1 25"): with a March year-end, Q1 25 = 2024-04-01 to 2024-06-30. Months stay calendar months. With December nothing changes.
- Every period resolves internally to a start date and an end date; a December year-end gives the calendar year. Forecast dates, value at stake (defined in docs/specs/forecast-claims.md, to be written) and comparisons with the revenue file use the range end and the months inside the range. Display keeps the text as stated.
- Relative columns ("M1…M24", "Year 1") → null unless the sheet states the start date in a cell.
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
- Since issue #45 the answer file gives the claims of §2's new types those types, and lists three more company
  claims: front-b p15 "$7m left" (cash) and "18 months" (runway), and moz p20 "~100" (trials per day, a usage figure
  before).
- Pass mark: the parser finds at least 95% of listed claims.
- Precision (false candidates) is reported; the test fails if it drops below 30%.
- Runs as a normal automated test.

## 4. What may reach the model
- The deck parser has no import of, or call to, the LLM gateway.
- Two paths reach the gateway, and each has its own fields:
  a) Narrative path: computed results from MongoDB and the structured claim fields (type, value, high value of a range, unit, date, status).
  b) Structure path (rule 16): redacted deck structures and spreadsheet header rows (at most 3) with, per column, either up to 3 sample values (numeric and date columns only) or a profile (distinct count, typical length, shape pattern) for text columns, as extracted text with cell positions, only with per-audit consent. Table cells, including a row's values by period, travel this path and no other.
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
- KPI panels: text boxes with a number beside a short label, and the label boxes and value boxes next to them.
- Roadmaps and timelines: text boxes with dates.
- Hiring, unit-economics and use-of-funds tables: tables classified by header keywords. Any other table is a table.
- Text that is none of these is prose and is never a structure.
Python assigns the type. The model may confirm or correct it in its type field, and Python logs any change.
The keyword lists, the label length and how many dates make a timeline are fixed on the 10 test decks at build time
and written into this section.
Fixed on the 10 test decks (2026-10-05):
- Table type: keywords in the header rows, the first column and the caption (the line right above the table, within
  a tenth of the page). Use of funds: use of funds, use of proceeds, funds, proceeds. Unit economics: CAC, LTV, ARPU,
  ARPA, ACV, payback, unit economics, contribution margin. Hiring: hire, hiring, headcount, recruit, recruitment,
  role, position, FTE (and plurals). The first match in that order wins.
- KPI panel: a text box of at most 4 lines, each at most 30 characters, holding a figure that is not a date and a
  word, and not one sentence wrapped over its lines (a line ends on, or the next starts with, a word such as "of",
  "and", "the", or a line ends with a comma). The KPI boxes of a page form one panel.
  The article "a" counts only in lower case (issue #50): a line ending on a capital "A" ends a name, so front-b p15's
  "Seed to Series A / $3.1m raised / $xx spent / $xx ARR added" is a KPI box, like its twin "Series A to date".
- Label boxes, value boxes and a title as label (decisions of 2026-10-06, issue #48). They only join a page's panel: a
  page with no KPI box has no panel.
  - Label length: 59 characters. The longest label on the 10 test decks is "Crawling, Serving, Hosting + Processing"
    (moz p21, 39 characters); 39 plus 50% is 58.5, rounded up to 59. It applies to label boxes and to a title used as
    a label. A KPI box's lines keep their 30 characters: at 59, bullet sentences on 20 more pages became KPI boxes.
  - Label box: a text box of at most 4 lines with a word and no figure other than a date, whose lines read as one
    line are at most the label length. So a label wrapped over two lines counts ("Spend as / % of revenue", front-b
    p12), and a wrapped sentence longer than that is prose and stays out. It joins the panel when it sits directly
    next to a KPI box or a value box.
  - Value box: a text box that holds one figure that is not a date, and no word outside it; a scale word such as
    "million" is part of the figure ("~13,500", "~82%", "$12 -$13 million"). It joins the panel when a label box sits
    directly next to it. A chart axis tick (§2) is no value box, and "3/1/15" holds three figures.
  - Directly next to: in the same band (the two boxes overlap in height), or directly above or below (they overlap in
    width and are at most a tenth of the page apart, as a table caption), with no other text box between them.
  - Title as label: when no label box sits next to a value box, a title line (the pptx slide title, the topmost text
    of a pdf page) directly next to it, in its band or above it, is its label, if the title has no figure other than
    a date and fits the label length. The value box joins the panel with it (moz p20: "2011 Estimated Revenue" beside
    "$12 -$13 million").
  - The title is sent marked as a title: its cell line is `r<row>c<col> title: <text>` (`r1c1 title: 2011 Estimated
    Revenue`), extending the cell-line format of llm-structure-reading.md §1 in `redact.structure_text`. A title cell
    is a label, never a value: the item list skips it and the gateway refuses an item line citing it (bad_item_line).
    The prompt's input section describes the marker (prompt v4, release r7), and
    backend/tests/test_gateway_data_boundary.py covers the title line (CLAUDE.md rule 14).
  - CLAUDE.md rule 16 holds: label boxes and titles become KPI panel cells, short, redacted and sent as extracted text
    with cell positions. A cell over 200 characters and a wrapped sentence still stay out.
- Roadmap or timeline: at least 3 date labels on the page (a line that is a date with at most two other words), once
  chart axes are left out (3 or more distinct dates, evenly spaced, in one line, row or column), and a product
  keyword (§2) on the page. It holds every box on the page whose lines are at most 60 characters.
- A structure holds at least one figure (a number or a date; list and row numbers do not count). A cell over 200
  characters is prose and is left out. A page whose figures §2 drops (background, cited research) holds no structure.
- Text boxes become a grid: boxes that overlap in height form a band, each box a column of its band, each line a row.
- In a roadmap, a paragraph is one row (issue #49). A pdf wraps a paragraph over several lines, and a row per line
  gave one milestone per line: moz p2's 9 dated paragraphs became 40 rows. A roadmap text box is one paragraph when it
  has two or more lines, none of them a date label, and each line after the first continues the one above: it starts
  with a lower-case letter or "&", or the line above ends with punctuation (. , ; : ! ? /, before any closing quote
  or bracket), with a wrap word (the KPI list above, "a" in lower case only) or inside a bracket it opened. Such a
  box becomes one cell: its lines joined with a space, in their order. Otherwise the box keeps a row per line: a line
  that starts with a capital letter or a figure after a line that ends with none of these starts a new item, as in a
  bullet list. A box whose joined text would be over 200 characters keeps a row per line too (a longer cell is
  prose, above). KPI panels keep a row per line.
  - On the test decks: moz p2's 40 text lines become 9 cells, one per dated paragraph. buffer p6 (one box that
    alternates lines and dates) and tea p11 (bullet lists, each bullet a capital letter after a line with no end
    punctuation) keep every line as a row, unchanged.
  - Known limit: in a bullet list, a bullet wrapped over two lines keeps two rows (tea p11: "from Hashkey",
    "economy", "layer-1 to layer-2").
- A band only knows heights, so a tall box can put two visual rows of a page in one grid row (issue #50). front-b p15:
  the box "“Default alive” † / Profitable in 10 months" spans the label row ("Cash on hand", "Runway *") and the value
  row ("$7m left", "18 months"), so the five boxes form one band and the grid row reads `Cash on hand | $7m left |
  18 months | Runway * | “Default alive” †`. So in a KPI panel each cell also keeps `next_to`: the ids of the cells of
  other boxes whose line is directly next to its own line, as above (same band, or directly above or below within a
  tenth of the page, with no other text box of the page between them), measured line to line, not box to box. A
  line with no position has no `next_to`. It is layout, stored with the structure and never sent to the model
  (structure-labelling.md §1 uses it for header cells). Roadmap cells keep `next_to` too, measured the same way
  (issue #56): a roadmap figure takes a header from a date box only when it sits directly next to it.
- Date boxes (decision of 2026-10-06 on issue #47, option a). In a roadmap, a date box is a text box each of whose
  lines is a date label or a part of one ("2022" / "Q2", "Nov. 2007"). Each line of a text box that is no date box
  also keeps `date_box`: the box number of the one date box directly next to its text box, measured box to box with
  the rule above (same band, or directly above or below within a tenth of the page, with no other text box of the
  page between them). A text box with no date box or two beside it keeps none. Like `next_to` it is layout, stored
  with the structure and never sent (structure-labelling.md §2 dates paired lines by it).
  - On the test decks: each of moz p2's 9 paragraphs has one (its date box above or below it); 21 of tea p11's 22
    bullet lines have one ("2021" / "Q2" and so on). "Mainnet starts" has none: its date box reads "2023" / "Q1-Q2",
    and "Q1-Q2" is no period part (§2), so the box is no date box. buffer p6 is one box and has none.
- On the test decks: 22 KPI panels, 3 timelines (moz p2, buffer p6, tea p11), 1 table, 1 hiring table. Neither pptx
  deck holds a native chart; chart reading is tested on built decks.
- Recounted with label boxes, value boxes and titles (2026-10-06): the same 22 KPI panels, 3 timelines, 1 table and 1
  hiring table. 13 KPI panels gain cells: front-b p12, p14, p15, p16, p18; moz p13, p20, p21, p23; zero2hero p11;
  genesisai-2021 p14; genesisai-2024 p14; tea p9. On moz p20 and p21 every label joins, the nine value boxes join
  with their labels (p20: "~13,500", "~100", "~$900", "~$100", "~$93"; p21: "~300K", "~82%", "~57%", "~25%"), and
  the title labels the first value ("2011 Estimated Revenue", "% of Free Trials Converting to Paid").
- Recounted with the wrap word "a" in lower case only (issue #50, 2026-10-06): the same 22 KPI panels, 3 timelines,
  1 table and 1 hiring table. front-b p15's panel gains the box "Seed to Series A" and its 4 lines; nothing else moves.

## Done when
- All three formats parse with correct slide/page references.
- Recall test passes at 95%+ with precision at 30%+.
- Isolation test passes.
- Approval list in the frontend shows candidates with their source reference.
- Upload screen shows the scope message.
