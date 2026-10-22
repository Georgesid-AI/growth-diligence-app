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
If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet."

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
- Sales: sales cycle, win rate, pipeline, ACV, payback, conversion, leads, and the verbs acquire, acquired, acquiring (the noun "acquisition" is no keyword since 2026-10-10: category names such as "Talent Acquisition" made Sales claims; "acquisition cost" and "cost of acquisition" stay CAC)
- Customers: customers, clients, paying users, accounts, companies, agencies, subscribers,
  institutions. A customers noun preceded, in its own cell or phrase, within 3 words and with no figure between them, by
  registered, signed-up, sign-ups, signups, onboarded, waitlist, waitlisted, pipeline, target, targeted, addressable,
  potential, prospective, trial or free (any case) is Users, and the word is kept lower case as the candidate's
  `qualifier` ("Registered Institutions": Users, qualifier "registered"; "Target 500 customers by 2025", a plan target,
  stays Customers; 2026-10-13, George, see the amendment at the end)
- Users: users
- Gross margin: margin, margins
- Gross profit: gross profit; also a gross margin given as an amount ("Gross margin £1.2M")
- Costs: direct costs, costs, opex
- EBITDA: EBITDA, profitability, profitable, break-even. "Profitable" with a figure in months is months to
  profitability (below).
- Net profit: net profit, net income, net loss. A net loss is stored as a negative net profit
  ("Net loss of $2M" → -2,000,000).
- People: hires, headcount, team, recruitment, attrition
- Product: launch, release, roadmap, ship, milestone. Q1–Q4 and month names give a date, and a line or box that holds
  one of the product words gives the Product type; a date word alone names no type (Unknown type, below).
- Market size (stored as `market`; shown as "Market size" since 2026-10-08, it was "Market"): TAM, SAM, SOM,
  addressable market, market size. The bare word "market" does not count.
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
Unknown type (2026-10-08, George): the type is never guessed. A figure whose own line has no claim keyword, and which
finds none in the text it may borrow from, takes the type Unknown ("Unknown – choose type") when its line holds a date
word (Q1–Q4, a month name); without a date word it is not a candidate, as before. A line whose only figures are dates
takes the same type when it has no keyword and borrows none ("Q3 2025" alone); with a borrowed keyword it keeps the
type it had. An Unknown claim is listed, cannot be approved as it stands, and is approved by an Edit that chooses a
type (the server answers 400 otherwise, as for the model's "other", structure-labelling.md §4). A date-only Unknown
claim with the same date as a Product claim of the deck is merged into it, as both were Product before, so no row
appears or disappears. Each candidate also stores `type_from`: "line" (its own line holds the keyword), "heading" (the
keyword came from borrowed text) or none (Unknown); the Confidence column reads it (§6). On the 10 test decks (measured
over `detect_candidates`, no network): 225 candidates before and after, recall 121 of
124 (98%) and precision 109 of 225 (48.4%) unchanged; 8 candidates change from Product to Unknown: front-b p11 "Q3 14"
and "Q3 15", moz p1 "July 2011" and p2 "Sept. 2010", clevergig p3 "The Economist, January 2015", uber p21
"SmartPhones, Aug2008", tea p12 "Completed May, 2021" and "Completed April, 2022". No other type changes.
Nearest heading (2026-10-08, George): a type is assigned only when the claim's own line or its nearest heading names it;
otherwise the claim is Unknown ("Unknown – choose type"). The nearest heading is the closest text on the page (the figure's
column header first; then, by distance on the page, the other lines of its text box, the boxes on the same row or above it
within a quarter of the page, and the slide title; with no layout, as in a .docx, the first in the order of borrowing) that
is a heading, a word with no figure of its own and at most 59 characters (the label length of §7), or that holds a claim
keyword; a line of figures or a sentence with no keyword is passed over. When that text names no type the figure takes none,
however clear a heading further away: zero2hero p11's "AR/VR ($52 B)" and "E-Learning Market ($374B)" sit under "Market"
(the bare word does not count), and the "Acquisition" of a box further up typed them Sales before; they are Unknown. A
figure whose only keyword is further away stays a candidate (type Unknown, no "Label from"); one with no keyword anywhere is
not a candidate, as before. The same rule types a date-only line and a figure-less milestone line. On the 10 test decks
(measured over `detect_candidates`, no network): 225 candidates before and after, recall 121 of 124 (98%) and precision
109 of 225 (48.4%) unchanged; 31 more candidates are Unknown (8 before, 39 after), among them front-b p14 "Team growth is built upon solid foundations" 5.0 and 100%, moz p21 "~$180K / Month"
(was Costs), zero2hero p11 "($52 B)" and "($374B)" and p22 "21%" and "11%" (Sales; Use of funds since 2026-10-10, below), uber p11 "Car services require 1-3 hours
notice" (Users). `type_from` is "line", "heading" (the nearest heading named it) or none (Unknown).
The unit of a count is the noun it counts: "800 paying users". If a Customers or Users keyword
appears within the next 4 words after the number, it is the unit (">50 Dutch temporary work
agencies" → agencies); otherwise the word right after the number. The search stops at the next
figure: a keyword after it belongs to that figure ("5 advisors & 15 clients" → 5 advisors).
There is no Usage type: a count whose line has no keyword borrows a label like any other
figure, or is not a candidate.
A line with its own keyword never borrows a label from other lines.
Periods are dates, never values: "Y/E 22", "22 Y/E", "FY23", "2023E" (also A, F, B, P),
"H1 24", "1H24", "Q3 25", "3Q25". A half year is stored as "2024-H1".
A date written with slashes, d/d/yy or d/d/yyyy (both parts 1 to 31, one at most 12: "5/1/18", "12/31/2018"), is a
date with no period (issue #53, option a, decision of 2026-10-07). The order of day and month is not stated ("5/1/18"
is 1 May or 5 January), so none of its parts is a figure, it is no period cell, no date label (§7) and nothing is
dated from it, the year of "12/31/2018" included. A pair with no year ("(1/2)") is unchanged. On the test decks:
front-b p14's axis dates ("3/1/15" to "11/1/17") and p16's ("1/1/18 5/1/18", "9/1/18 12/1/18" and the four dates on
lines of their own) give no candidate: 236 candidates become 225 (p14: 6, p16: 5 fewer). Recall stays 121 of 124;
precision goes from 46.2% to 48.4%.
Period rules (apply to tables, structure text and the verifier):
- Header stack: extracted structure text includes every header row above the data; a merged range is written with its span, e.g. "FY2025 (r1c3:r1c14)". The model receives the full header stack, not only the row directly above the values. The column-mapping path has its own cap (llm-structure-reading.md §1).
- "Q1-Q2" reads as the first half-year and "Q3-Q4" as the second (issue #55, decision of 2026-10-06): a period part like "H1" ("2023" over "Q1-Q2" → 2023-H1), and on one line with its year, before or after it ("Q1-Q2 2023", "2023 Q1-Q2"), 2023-H1 (both read 2023-Q1). Any other quarter range ("Q2-Q3", "Q1-Q4") has no period (decision of 2026-10-07): it is no period part, nothing is dated from it on one line with a year ("Q2-Q3 2023" read 2023-Q2), and its year is no figure. On the test decks only tea p11's "Q1-Q2" exists, a line of its own under "2023". "Mainnet starts" borrows "2023 Q1-Q2" from its box, so its candidate's date goes from 2023-Q1 to 2023-H1, and the answer file follows (§3); no other candidate changes (225), and `--fake` is unchanged.
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
Bars (2026-10-09, George): a figure that sits above a bar with a year label under it ("2021", "FY2022"; two or more such
labels on one line make the axis, each nothing but a year, the figure overlapping one of them from side to side, at most 0.6 of
the page above it) takes that label as its date, after the figure's own date, its column header and its box period and before
any text further away. It is a real date ("stated", George 2026-10-09), so it is compared for a Deck inconsistency with other pages;
confidence is scored with the date attached ("no date" no longer fails). Measured on the 10 public test decks
(2026-10-09, `detect_candidates` with and without the rule): 3 of 225 candidates change, all zero2hero p17 (Turnover (£/year):
278,085 → 2021, 415,107 → 2022, 550,508 → 2023, shown "2021"… instead of "per year"); no other deck changes. Compared with page 19's table, the 2022 and 2023 bars (415,107, 550,508) are flagged and page 19's Revenue row gains the dates 2022 and 2023. The p17 bars
for 2019 and 2020 (49,284, 181,193) are not candidates, being too far from the heading to take its type, before and after.
A date is taken first from the figure's column header, then from a period line at the top of
its text box ("23 Y/E" over "Gross Profit £150K" and "5K Users"), then as above. The box period
dates figures only; the period line itself is never a candidate.
The snippet is the figure's own line. A borrowed label is kept apart and shown below the
snippet as "Label from: <text>"; a borrowed date as "Date from: <text>". "Label from" is the single heading that names
the type, not every heading of the box or of the slide title (2026-10-08, George). A box or title of at most 59
characters (the label length of §7) is one heading, wrapped over its lines ("Spend as" / "% of revenue"); a longer
one holds several, and the heading is the line that holds the keyword (the lines it runs over, if the keyword wraps:
"MARKET" / "SIZE"). The search order is unchanged, so no type changes. On the 10 test decks 22 of the 225 candidates
show a shorter "Label from", and the labels of 40 characters or more go from 31 to 17 (moz p2 "SEOmoz launches its first
subscription software product, …" → "SEOmoz launches its"; tea p11 three bullets → the one line with the keyword; the
front-b tag list "Tech Media Travel Client Services …" → "Client Services Ecommerce …").
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
Duplicates are merged and keep all source references, across slides and on one page: the same type, value, unit, currency
and period is one claim and one row listing every source (2026-10-08). A duplicate is never a Deck inconsistency; the
mark below applies only to differing values. Amended 2026-10-20 (George): a figure read at two precisions (501,378 and 501,378.04) is
the same claim when the type, unit, currency and period are the same, the values are equal after rounding to whole units and a
page or slide is shared; the more precise value is kept and the other's source location joins the sources. Money amounts only: never a
rate, a ratio or a count, never across pages or periods, never the values of a table row by period. The same holds across the two reading paths (2026-10-08, George): a value the
model read from a structure (a KPI panel, a table, a roadmap) that the parser already lists, or that an earlier row of the
deck lists, with the same type, value (range included), currency and period (and the same kind of unit when it is a rate or a
multiple), is not a second row: the model's cell is added to the sources of the row that exists, and the row keeps its own
reading label (the parser's, which Python made itself). A claim with no value (a milestone, a direction) never merges: two
lines with the same date are not one claim. A value the parser lists in the same cell was already skipped (structure-labelling
§1). Example, zero2hero p19: "Gross Profit £150K" (23 Y/E) from the slide text and from the KPI panel is one row citing the
text and the panel's cell; it still carries "Deck inconsistency 2023" because the page's table gives £ 50,000 for the same
period, a differing value. On the test decks every value the model read on zero2hero (p19's gross profit and users among them) and moz p20's
"$12 -$13 million" range become sources of the parser's rows; the model's rows the parser does not list (moz p20's panel, front-b
p15, Buffer p6, moz p2) stay.
Dropped, never listed:
- Chart axis ticks: 3 or more numbers, evenly spaced in value, in one line, in one column or
  row of lines that hold only a number, or in one table column (row numbers 1, 2, 3). A table
  row is a series of values and the header row holds labels: neither is ever ticks.
  Added 2026-10-21 (issue #143): also a run of 4 or more round, equally spaced numbers, each alone in its line, anywhere on one page
  (0, 2,000, 4,000 ... 10,000; the step is 1, 2, 2.5 or 5 times a power of ten and the run starts at a multiple of it), whatever
  their positions. The number of a list item ("1.", "#3:", "2)") is no figure of such a run. A line with a word or a table cell is never one.
- Every figure on a slide or page titled Problem, Why now, Trends, Landscape, Background,
  Token or Allocation (pptx titles and the topmost text of a pdf page; docx has no titles).
- Every figure on a slide or page that cites outside research: a "Source:" or "Via <link>"
  line, or two or more footnote lines ("1. …", a bare link).
- Figures in a line about funds raised (raise, funding, investment, investors, valuation, seed
  round, Series A–D), tokens (token, allocation, vesting, total supply, lockup), people's careers
  (founder, CEO, chief, former, previously, employee, exec team) or the industry and the world
  (industry, global, worldwide, economy). This also drops other companies' figures quoted in
  founder bios.
Direction only (2026-10-08, George): "Positive EBITDA" or "EBITDA negative until Q4 2024" states a direction and no figure.
It is a candidate with no value, a `claim_direction` ("positive" or "negative") and the date it borrows or states, and
nothing else is read into it ("profitable" and "break-even" stay EBITDA milestones with no direction). Its value shows
"positive (no figure)" or "negative (no figure)", its confidence is at most Medium (the failed check is named "no figure"),
and in the claim register it is Unverified and never Verified or Contradicted (claim-matching.md §4). An edit that types a
figure ends the direction. On the test decks only zero2hero p19's "Positive EBITDA" (Q2 2024) has one.
Deck inconsistency: when one deck gives the same type and period different values (the page 19
panel's Gross Profit £150K for Y/E 23, the table's £ 50,000), every candidate holding one of them
is marked "Deck inconsistency" with that period. Only stated periods are compared: the figure's
own date, its column header's or its box's period. A date borrowed by position or from the
title is not, and neither are amounts in different currencies, or a rate and an amount. A figure whose label or
line holds a turnover term (turnover, GMV, TPV, volume; and no ARR or MRR) is "Turnover", any other revenue-type figure is
"Revenue": the two are never compared with each other (amended 2026-10-09, George; claim-matching.md §11). The
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
- Since issue #55 the answer file dates tea p11's "Mainnet starts (2023 Q1-Q2)" 2023-H1, the first half (§2).
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
  b) Structure path (CLAUDE.md rule 16): what its text may hold is defined in llm-structure-reading.md §1 (structure text, item list, column-mapping header rows) and §3 (redaction). Table cells, including a row's values by period, travel this path and no other.
- The boundary test (llm-structure-reading.md §10) fails the build if the parser imports the gateway, if the gateway reads parsed-text, snippet or source-reference fields, or if the structure path sends anything §1 does not allow. The narrative path is unchanged.
- Storage and verification follow CLAUDE.md rules 17 and 18; what is stored is listed in llm-structure-reading.md §9 and structure-labelling.md §5.

## 5. Storage and deletion
- Parsed text and candidates are stored in MongoDB, linked to the audit. An audit can hold
  several decks (needed later for the forecast track record).
- The "delete audit" button also removes parsed text and candidates.
- A "Remove deck" button per deck, after the confirm step "This deletes the deck and all its
  claims, including reviewed ones.", deletes that deck's parsed text and all its candidates,
  reviewed ones included (DELETE /api/audits/{id}/decks/{deck_id}).

## 6. Approval
Shown above the approval list, word for word (amended 2026-10-09, George; the Approve, Edit and Reject lines follow it unchanged):
"Claims found in the uploaded documents
These figures were extracted automatically and inform the growth plan. While errors are possible, you only need to check claims that look incorrect or implausible against their source slides before making your selection."
✓ Approve: Confirm this is a claim the company makes. It will be added to the claim register and tested against the data.
✎ Edit: Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data.
✕ Reject: Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used.
- Add claim (2026-10-09, George): a button beside that text opens one row: metric (the type list below), value or range, unit,
  currency, date or period, source document (a dropdown of the audit's uploaded documents) and page number. Source document and
  page are required, and so is the value and the metric the claim is tested against (claim-matching.md table 2a, only those in the
  claim's unit; no default, George 2026-10-09), stored as the analyst's metric. POST /api/audits/{id}/decks/candidates stores it approved, with `origin` "analyst", the
  snippet "Added by analyst", the source {file, slide or page, kind "analyst"} and the confidence "Analyst-entered" (not scored).
  It is in the register at once and is matched and labelled by the same code as every other claim, with its metric set by the analyst. In the register and the CSV
  its `deck_reading` is "analyst-entered" (also after an edit). Removing its deck removes it.
- Approve: status "approved".
- The type list the analyst chooses from is the plan claim types of §2 with "Market size" for `market`; "Unknown –
  choose type" and the model's "Other" are listed but are not choices.
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
- Order (amended 2026-10-08, George, twice): the claims table is grouped by type, then ascending by slide or page number.
  Groups (decision of 2026-10-08, George, second version): 1 revenue (ARR, MRR, revenue, bookings: type Revenue and Revenue
  growth); 2 P&L items (gross profit, EBITDA, burn, cash, runway, and with them costs, net profit, gross margin and months to
  profitability); 3 customers, users, usage, NRR, churn, pipeline, sales cycle (types Customers, Users, Usage, User growth,
  Growth, Retention, Sales, LTV, CAC, LTV/CAC, Customer lifetime, Trials per day); 4 hiring and roadmap (People, Product: hires
  and launch dates); 5 market size; 6 Unknown; 7 Other (the model's "other" and Use of funds). Under "All" the pages run across all decks (a tie goes to the more recent deck), and within each deck
  tab. Within a page the order is reading order: top to bottom in bands of 2% of the page height, then left to right, then the
  order the parser found them in (a claim with no layout, as in a .docx, keeps that order). A claim with several sources sits
  at its first page. To review no longer comes first, and a reviewed claim does not move except when its type is edited into
  another group. Groups 6 and 7 are collapsed by default under a header with their count ("Unknown – choose type (12)"); the
  analyst opens them. The server sorts and sends `group` (1 to 7) with each candidate; it is layout only, never sent to a
  model.
- Status column (2026-10-09, George): the status (To review, Approved, Edited, Rejected) is a label, not a control: plain
  coloured text with no border or chip, so it never reads as a button. Approve, Reject and Edit are the buttons of the
  Action column; a turnover claim asks Revenue or Volume in its row (claim-matching.md §11 point 8).
- Period column (2026-10-08, George): the column "Date" is "Period". Every value reads in one format from the stored target
  date, whatever the deck's wording: a year "FY2023", a quarter "Q2 2024", a half "H1 2024", a month "Jun 2024"; a table row
  shows its first to last period ("FY2022–FY2026"). "no date" only when the deck gives no period (2026-10-09, George; it was "—"). The deck's own wording ("Y/E 22",
  "FY25") stays in the snippet and the "Date from" line.
- Value column and currency (2026-10-08, George): a claim in a currency other than the audit's shows both figures, the claim
  converted at the saved FX rate, in whole units: "150,000 GBP (171,000 EUR)". The rate and the date it applies at (the as-of
  date) are on hover, never in the row, and stay in the stored citation and the memo (2026-10-09, George). With no rate saved it
  reads "150,000 BRL (BRL→EUR rate missing – enter it in FX settings at the top of the page)", "FX settings" being the link, and
  the claim is Unverified in the register (claim-matching.md §2). A direction with no figure reads "positive (no figure)".
- Cost (2026-10-08): the deck panel's "Cost" line shows dollars to 2 decimals ("Cost: $0.01"). The server sorts; each candidate stores `reading`
  (top, left of its first line; for a model row, of the parsed line it cites), layout only, never sent to a model.
- Confidence column (2026-10-08, George), after Period: High, Medium or Low, computed on read from checks Python
  already runs, never from a model's own score: (1) a date is present; (2) a unit or currency is present; (3) a line
  or heading names the type (`type_from`; for a model row a header cell or a keyword in its own text; an edited claim
  counts as named; a claim stored before this column has no `type_from` and counts as named unless Unknown or Other);
  (4) the value is corroborated elsewhere in the deck: another source of the merged claim on another slide or page,
  or another candidate of the deck with the same type, value, unit and currency at another place (the cells of one
  table row are one place). A claim with no value skips (2) and (4). No failed check is High, one Medium, two or more
  Low, and the failed checks are named: "High", "Medium – not corroborated", "Low – no date, no heading". The names
  are "no date", "no unit", "no heading", "not corroborated" and, for a direction with no figure, "no figure" (so it is never
  High). The column is not an input to claim matching, and
  nothing of it reaches the gateway (test_gateway_data_boundary.py names `confidence`, `type_from` and `reading`).

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
    directly next to it. A chart axis tick (§2) is no value box, and "3/1/15" is a date with no figure (§2).
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
- In a roadmap, a paragraph is one row (issue #49), and so is a bullet (issue #55). A pdf wraps a paragraph or a bullet
  over several lines, and a row per line gave one milestone per line: moz p2's 9 dated paragraphs became 40 rows, and
  tea p11's wrapped bullets could pair their second line ("from Hashkey") as a milestone of its own. A roadmap text box
  splits into items at each line that does not continue the one above. A line continues the one above when it starts
  with a lower-case letter or "&", or the line above ends with punctuation (. , ; : ! ? /, before any closing quote
  or bracket), with a wrap word (the KPI list above, "a" in lower case only; a line ending on a figure, "Second
  milestone ongoing in 2021", ends on no word) or inside a bracket it opened. A date label is an item of its own and
  is never joined. Each item becomes one cell: its lines joined with a space, in their order. A paragraph is the box
  of one item; in a bullet list a line that starts with a capital letter or a figure after a line that ends with none
  of these starts a new item. An item whose joined text would be over 200 characters keeps a row per line (a longer
  cell is prose, above). KPI panels keep a row per line.
  - On the test decks: moz p2's 40 text lines become 9 cells, one per dated paragraph. buffer p6 (one box that
    alternates lines and dates) keeps its 12 rows, unchanged. tea p11's three wrapped bullets become one cell each
    ("Seed round secured including investment from Hashkey", "Begin Go2Market strategy starting with miners'
    economy", "Majority of business logic migrated from layer-1 to layer-2"): 38 cells become 35, 30 text lines 27.
  - Known limit: a bullet that starts with a lower-case letter joins the bullet above. No roadmap bullet on the test
    decks does. Across every text box of the 10 test decks, 192 lines start in lower case after a line with no end
    punctuation, wrap word or open bracket: wrapped sentences and pdf letter fragments, and one probable bullet
    (buffer p10 "in talks with Reeder, Pocket and Feedly" under "6 integrations so far", on a page that is no
    roadmap).
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
  - On the test decks: each of moz p2's 9 paragraphs has one (its date box above or below it); each of tea p11's 19
    bullet lines has one ("2021" / "Q2" and so on). "Mainnet starts" has one since issue #55: its date box reads
    "2023" / "Q1-Q2", and "Q1-Q2" is the first half (§2). buffer p6 is one box and has none.
- On the test decks: 22 KPI panels, 3 timelines (moz p2, buffer p6, tea p11), 1 table, 1 hiring table. Neither pptx
  deck holds a native chart; chart reading is tested on built decks.
- Recounted with label boxes, value boxes and titles (2026-10-06): the same 22 KPI panels, 3 timelines, 1 table and 1
  hiring table. 13 KPI panels gain cells: front-b p12, p14, p15, p16, p18; moz p13, p20, p21, p23; zero2hero p11;
  genesisai-2021 p14; genesisai-2024 p14; tea p9. On moz p20 and p21 every label joins, the nine value boxes join
  with their labels (p20: "~13,500", "~100", "~$900", "~$100", "~$93"; p21: "~300K", "~82%", "~57%", "~25%"), and
  the title labels the first value ("2011 Estimated Revenue", "% of Free Trials Converting to Paid").
- Recounted with the wrap word "a" in lower case only (issue #50, 2026-10-06): the same 22 KPI panels, 3 timelines,
  1 table and 1 hiring table. front-b p15's panel gains the box "Seed to Series A" and its 4 lines; nothing else moves.
- Recounted with dates written with slashes (issue #53, 2026-10-07): 21 KPI panels, 3 timelines, 1 table and 1 hiring
  table. front-b p16's panel ("Cash", "1/1/18 5/1/18", "9/1/18 12/1/18", "Gross margin", "Operating margin") holds no
  figure once its dates are dates, so it has no KPI box and is no panel; nothing else moves.

## Done when
- All three formats parse with correct slide/page references.
- Recall test passes at 95%+ with precision at 30%+.
- Isolation test passes.
- Approval list in the frontend shows candidates with their source reference.
- Upload screen shows the scope message.

## Amended 2026-10-09 (George): explanation, label brackets, count unit, moved claims
- Deck inconsistency: every flagged claim carries `inconsistencies`, the two figures compared (value, currency, unit, date,
  place and, for a revenue-type figure, the deck label "Turnover" or "Revenue" of each). The tag shows "The deck gives
  different figures for this metric: [label] [value A] at [location A] and [label] [value B] at [location B]." (for example
  "Turnover 550,508 GBP at d.pdf · page 17 and Revenue 150,000 GBP at d.pdf · page 19"; Turnover is compared with Turnover and
  Revenue with Revenue only) on hover and in the opened row. The tag is never shown without it. The parser compares only figures with the
  same type, currency and period and different values, so a pair always has two different values (the same-value wording was
  deleted 2026-10-09: it could not be reached). Decks parsed before this change have no pairs and show no tag
  until they are uploaded again.
- Confidence: a currency or period in a label's brackets ("Turnover (£/year)") is read before scoring: the currency fills an
  empty currency field (GBP) and the period goes to `period_basis` ("per year", "per month", "per quarter"), shown beside the
  date, except "per year" beside a year, which adds nothing (2026-10-09): "per year" shows only when no year is found. Scale brackets ("(€m)") are not read. The date stays missing when no year is given. The reason lists only what is
  still missing.
- Unit: "count" joins the unit suggestions (customers, headcount, deals); currency stays its own field.
- A claim that is approved or edited and moves to another category (by a changed type) shows "Claim moved to [category]" with
  Undo for 4 seconds and its row is highlighted for the same time; Undo restores the previous type.

## Amended 2026-10-10: Use of funds (bug: zero2hero p22 "Investor Proposition")
- Cause. On p22 the use-of-funds percentages were typed Sales by the keyword rule of §2, not by any of the three suspects: the
  Sales family holds "acquisition", and the category names "Content Acquisition & Development" and "Operational Expenses &
  Talent Acquisition" carry it; the pie's labels 42% and 26% then borrowed the nearest heading, "Content Acquisition &
  Development (20%)" (Sales), and 21% and 11% were left Unknown. There is no rule that reads a money figure plus percentages
  summing to 100 as revenue by segment; `use_of_funds` was already in the structure reading's metric list; and the funding
  cue words only drop lines about funds raised (§2, "Dropped") and type structures (§7), they never typed a claim.
- Claim type **Use of funds** (stored `use_of_funds`): an allocation share of a raise. Unit %, no engine metric, listed under
  Other, never Sales or Revenue. In the claim register it is Unverified (reason: "use of funds: an allocation share of the
  raise, no engine metric to test it against"), has no gap and no value at stake, needs no gate, ranks after every other
  claim, and is left out of the top 5 (the proposal, the banner's rows 1-5, the confirmed set and the verdict).
- Trigger, per slide or page (changed 2026-10-10, George; the cue list replaced the same day, and again after the review of PR 86). A
  cue phrase is required, as whole words in any case. Phrases of several words: use of funds, use of proceeds, the ask, our ask,
  funding ask, investment ask, funding request, capital raise, funding round, proposed financing, round details, round size, raise
  size, funding requirements, capital requirements, capital sought, funding sought, sources & uses, sources and uses, investor
  proposition. They count in the slide's title, in a heading or in a table's header row. The single word
  "raise" counts only in the slide's title, never in a heading or a table's header row (a table's merged title row is a heading). "Investment opportunity" and "financing" are
  not cues (they name slides that are often not raises). A heading is a short line (at most 59 characters) with no figure that sits
  ABOVE the first percentage of the slide, does not start with a bullet, dash or asterisk, and holds the cue phrase and at most 3
  other words ("Use of funds - Series A"; "The ask from users is simple" is not one). Body text and footnotes never carry a cue:
  "We plan to raise prices next year", "Raise brand awareness in Europe" below the figures, "* post-raise runway", "raised prices",
  "refinancing" and "We raised Series A in 2023" are no cue. Without a cue nothing is a
  use of funds, whatever the percentages sum to and whatever amount the slide shows; a raise amount (a figure with a currency) and
  percentages summing to 95-105 may only confirm a cue and change nothing. With a cue, every percentage on the slide is a use of
  funds and is listed as one, also when no keyword or heading names it (p22's nine percentages stay candidates after "acquisition"
  left the Sales list). A percentage on a line with a growth, retention or margin word ("retention 90%") is a rate, never a share.
- On screen (2026-10-10, George). The edit form's type select shows "Use of funds" for these claims and the server accepts the
  type on save, so correcting a value (text 40% against chart 42%) keeps the type and the claim stays out of the top 5, the banner,
  value at stake and the verdict. "Use of funds" is not offered as a type to choose for another claim. The top-5 replace dropdown
  (`candidates` of GET /verdict) lists no Use of funds row.
- Block rule. If the slide's title, a heading or a table's header row holds revenue, sales, turnover, ARR, MRR, bookings,
  customers, segment, geography, country, region, product line or "by year", or the slide holds a run of 3 or more different year
  labels (2022, 2023E, FY24; the labels of the percentages count here), the percentages are a split of something else and are
  never typed Use of funds. Without a cue they keep the type they had before. With a cue as well (both appear) the slide is "mixed":
  its percentages are typed Unknown, carry `mixed_slide` and show the tag "mixed slide – check" in the claims list. The analyst
  chooses the type. The label attached to a percentage is not a heading and never blocks: "Sales & Marketing 30%" on a cue slide
  stays a use of funds, and so does a legend entry beside or below the percentages. A heading counts only above the first
  percentage on the slide ("Revenue by geography" over the chart blocks; the same words in the legend do not).
- On the 10 test decks only zero2hero p22 is affected by this section: its 9 percentages (Sales or Unknown before) are Use of
  funds, Unknown 39 → 37, 225 candidates before and after. Removing "acquisition" from Sales changes no other candidate.
- Deck inconsistency, text against chart. On a use-of-funds slide, when the text lines and the chart's labels give different
  percentages, each figure of the pair carries the tag with `inconsistencies` = `{this, other, note}`: `this` and `other`
  hold the figure with its deck label "text" or "chart" ("text 40% at d.pdf · page 22 and chart 42% at d.pdf · page 22").
  The chart's labels carry no category names, so the two sets are paired in order of value, and only when the chart has
  the same number of figures or one fewer. With one fewer, if every text value rescaled to 100 after dropping one category
  rounds to the chart's value (p22: 40/20/25/10/5 and 42/21/26/11, 40/95 = 42%), `note` is "chart excludes <category>,
  rescaled" and the tag text ends "...; chart excludes <category>, rescaled." The dropped category's own figure carries no
  tag. If two different categories would fit, or the counts differ by more, nothing is paired and nothing is tagged.
  Equal sets are not an inconsistency. The label stays Unverified: never Contradicted. Native pptx charts are structures
  (§7), not candidates, so this compares text and chart labels the parser reads as text (pdf, docx).
- Tests: `test_deck_parser.py` (p22 on the test deck, built slides for the cue and where it counts (a sentence above the figures,
  a bullet or footnote below them, a slide titled "Raise"), the block words, revenue by year and by geography
  and "acquisition", and the text 40/20/25/10/5 against the chart 42/21/26/11), `test_claim_matching.py` and `test_verdict.py` (register and top 5),
  `test_gateway_data_boundary.py` (the reason, `mixed_slide` and the note reach no gateway payload or log), `DeckPanel.test.jsx` (tag text, the edit form).

## Amended 2026-10-11: categories and Acquisition channels
Use of funds is its own section on screen (group 8) and Acquisition channels a new one (group 7), both directly above Other (now group 9); Unknown (6)
and Other (9) start collapsed, so "Groups 6 and 7 start collapsed" in section 6 reads "6 and 9". The new claim type, Approve all and the spacing are specified in
docs/specs/chat-upload.md section 17.

## Amended 2026-10-13 (George): non-paying customer labels
A customers noun that a qualifier precedes with no figure between them (section 2: "Registered Institutions", "40 trial accounts",
"pipeline companies"; not "Target 500 customers") counts people who are not paying customers: the figure is typed Users and keeps the qualifier as `qualifier` (one word of the closed
list, never other deck text; not gateway-readable). Two figures that differ only by the qualifier are neither merged nor compared
for a deck inconsistency. In the register a Users claim with a qualifier is Unsupported, reason "deck label '{qualifier} {noun}'
is not paying customers; the analyst can edit the type to Customers to test it" (claim-matching.md section 4); an edit to
Customers tests it as any customers claim. A claim with no qualifier is unchanged. Tests: `test_deck_parser.py` (each qualifier,
the 3-word reach, the phrase break, a column header, zero2hero p19), `test_claim_matching.py` (the row "Registered Institutions |
- | 1 | 2 | 25 | 50" and "Paying customers | 10 | 20"), `test_gateway_data_boundary.py` (the reason holds two closed words; the
qualifier reaches no gateway read, payload or log).
The same rule applies to a model-read claim (structure-labelling.md): one the model labels `customers` whose row header or own
cell holds a qualified customers noun is Users with its `qualifier`, so it is tested like the parser's and merges with it.

## Amended 2026-10-20 (George, 2026-10-19, issue #136): figures that share one table cell
A borderless PDF table can be read with a row's figures in one cell, under a header cell that holds every period. Before, every
figure of the cell took the header's first period (four quarterly values all read as Q1). Now the k-th figure of one unit and currency
in a cell takes the k-th period of its column header, or of the header cells from its column rightwards, when the counts match;
otherwise none of them takes a period (no fallback: claim-matching.md table 2b, "Period not read – set it in the claim row") and
the value's shown period is empty. A figure with a date of its own is unchanged. A revenue-type figure whose label or line holds a
contract-value term reads "Contract value" for the deck inconsistency rule, so it is never compared with a revenue figure.
Tests: `backend/tests/test_issue_136.py`.
Amended 2026-10-20 (George, finding A and finding D after issue #136; tests `backend/tests/test_pdf_shared_cell.py`,
`backend/tests/test_unit_economics_pipeline.py`):
- A figure of such a cell whose header holds a different number of periods than the cell holds amounts has no period and carries
  `period_unclear`; the register reads it "Period unclear – confirm" (claim-matching.md table 2b). The synthetic PDF of the artefact's
  shape (a ruled two-column table, label in col 1, four amounts in col 2, four quarters in the header's col 2) paired correctly on main
  (b094fc2); the real deck is not reproduced.
- Two claim types are added to CLAIM_TYPES after months_to_profitability, in group 3 with LTV and CAC: `arpa` ("ARPA", revenue per
  account, client or customer) and `arpu` ("ARPU", revenue per user). Their keywords are ARPA, ARPU and "per account / client /
  customer / user", alone or after revenue, sales, income or spend; the phrase is longer than "Revenue", so a title such as "Average
  Revenue Per Account" types its bars `arpa`, never Revenue (longer keyword counts).
- A third type `pipeline` ("Pipeline", group 3) has the keywords "size of opportunity", "opportunity size", "weighted in forecast",
  "weighted pipeline" and "weighted opportunity / value". A table column header names a figure's type before the page title, so the
  columns of a pipeline table under a revenue title are Pipeline, never Revenue or Bookings. The bare word "pipeline" stays a Sales
  keyword.

Amended 2026-10-20 (George, review of the unit-economics change; tests `backend/tests/test_unit_economics_pipeline.py`,
`backend/tests/test_structure_reading.py`):
- A title, header or line types `arpa` or `arpu` only for "ARPA", "ARPU", "average revenue per", or a revenue word (revenue, sales, income,
  spend, ARR, MRR, bookings) followed by "per" or "/", at most one of paying, active, new, existing or average, and the noun account, client,
  customer or user where that noun ENDS the phrase (nothing, a mark, a figure or a period word such as "by year" follows). "Revenue per
  customer segment", "per client type", "per customer cohort", "per user group" stay Revenue; "Seats per account" is no unit economics.
- A column header "Revenue per client" over rows that name a client ("Acme") types each figure Revenue; over rows that are periods it stays ARPA.
- Amended 2026-10-21 (issue #143): the bars of one chart row share the chart's caption. A bar with no heading within reach of its own
  (further than 0.25 of the page from a caption such as "Average revenue per account (EUR)", at the far end of the row) takes the
  headings near its row mates before the page title, so a title such as "2022 FORECAST: CLIENT COMPOSITION" no longer types the far bars
  Customers or Revenue while the near ones are ARPA.
- A model label of arpa, arpu or pipeline stands only when the cell or one of its headers holds the keyword; otherwise it is listed as Other.

Amended 2026-10-20 (George): a figure under a pipeline column header ("Size of opportunity", "Weighted in forecast") is Pipeline whatever its
row label says ("ARR expansion Acme"); the header wins over the row's own keyword for that type only. Test: `test_unit_economics_pipeline.py`.

Amended 2026-10-21 (George, issue #146): (1) the deck upload box is a drop zone: a file dropped on it takes the path of the picker, with the same
types (.pptx, .docx, .pdf) and the same refusal message. (2) A candidate with no figure is dropped when a figure on the same page already uses its
line as its "Label from" ("2020 REVENUE" over "151K"): the figure is the claim, the heading only names it. A heading read on several pages loses the
pages whose figure uses it. A direction ("Positive EBITDA"), a product or milestone line and every other candidate with no figure are kept. A heading that no figure uses stays a claim and is scored
Medium with the reason "no figure", like a direction (George, 2026-10-21); a product or milestone line is scored as before. On the
10 test decks two headings go (02-moz p20 and p21). (3) Confidence of a claim the analyst edited reads "Analyst-edited", like "Analyst-entered" for an
added claim; the claim is not scored again. A claim the parser read is scored as before. Tests: `test_issue_146.py`, `DeckPanel.test.jsx`.


Amended 2026-10-21 (George, PR 147 review): (1) several files dropped at once are accepted and uploaded one after another in drop order, with a status line per
file (uploading, done, refused type, failed); a refused type or a failed upload does not stop the others (like the xlsx upload). (2) A figure uses a heading when its
"Label from" is the heading's whole line, not a longer line that holds it. (3) A candidate with no figure is a milestone line, and not a heading, when it is a product
line, a line of unknown type or has a break-even cue ("profitable", "break-even", in its line or the heading it borrowed); the claim type "ebitda" alone does not decide
(a "2023 EBITDA" heading no figure uses is scored Medium, "no figure"; "Profitable by 2024" above a figure is kept).
## Amended 2026-10-21 (issue #148): year ranges, bars by position
- A range of years ("2022–2024", "2022 -2024", "2022 to 2024", "FY22–24", "FY2022-2024") is a date with no period, like a quarter range that is no half
  (`no_period_dates`): nothing is dated from it, its years are no figures ("FY22–24" no longer leaves a figure 24) and a heading that holds one gives no
  year to the figures under it; a figure under it takes its own year, its column header's, its box's or its bar's, else none ("Period not read",
  claim-matching.md table 2b). "2022-03" is a month, "FY2024/25" one fiscal year: unchanged. Found on the ten test decks: "(2011-13)" (02-moz p18)
  gave its figure 13 and the year 2011 to the three percentages under it.
- A bar takes its year by position as well as by overlap: the figures above one row of two or more year labels (the row nearest below them, between
  its first and last label, one label's spacing beyond) that are a figure and nothing else ("€1.48MM", "$210B"; never a sentence that holds a number)
  take the labels left to right when they are as many as the labels, overlapping or not. Any other count: only a label the bar overlaps. Axis ticks
  are not bars. Found on the ten test decks: the two market bars of 09-genesisai-2024 p4 take 2020 and 2030.
- A KPI panel's cell keeps its bar's year (`bar_year`, `claims.bar_years`) with the structure; it is never sent to the model (boundary test). The
  verifier dates the item from it after its period headers, its own cell and its adjacent date line (structure-labelling.md §4): code assigns the
  years by position, the model's period is corrected to it. Tests: `backend/tests/test_issue_148.py`.

Amended 2026-10-22 (issue #151; tests `backend/tests/test_issue_151.py`): (1) the deck label of a revenue-type figure (`deck_label`) is "MRR", "ARR" or "New MRR" when its own
label or line holds that term (also "monthly / annual recurring revenue"), before "Turnover" and "Revenue"; a contracted or committed MRR or ARR, including the bracket form
"MRR (contracted)", stays "Contract value". The claim type stays Revenue (its family covers ARR, MRR and bookings). Figures with different labels are never compared for a
deck inconsistency, so monthly MRR is not set against annual revenue. (2) An MRR or ARR figure whose own line says "in <year>" is the run rate at the end of that year: target
date <year>-12 (Dec), and the candidate keeps `period_read_note` = "period read as Dec 2021 from 'in 2021'". A month the deck states, "MRR 2021" without "in", and every other type keep
their period. The analyst's edit of the date replaces it and clears the note. Rules read and panel read (`candidate_from_item`) share `recurring_year_end`. Ten-deck pin: 212
candidates before and after, no claim type or date moves; the deck label of 7 rows moves from Revenue to MRR or ARR (PR for issue #151).
