# HRPulsar Features

HRPulsar is an open source platform for talent and competency management. This page describes what each module does in the current release. For installation see [Getting Started](/docs/getting-started); to run it on your own servers see the [Self-Hosted Guide](/docs/self-hosted).

---

## Employee Management

### Employee Profiles

A central record for every person in the company: position, division, hire date, status, and avatar.

- Three ways to add an employee: send an email invitation (the card is created when the person accepts), create a card manually for an existing user, or import a list from a file — each imported person is emailed a link to set their password
- Status lifecycle: active, on leave, inactive, terminated. Inactive and terminated accounts lose access immediately, and the employee is notified by email
- The profile header shows five summary tiles: Status, Tenure, Assessments, Goals progress, and Last assessment. Tile counts respect role visibility, so employees never see drafts hidden from them
- Goals progress averages completion across the employee's open development plans; a hint next to the tile explains the formula
- Last assessment counts completed assessments only, dated by their completion — the same rule the "no recent assessment" badge uses, so the header and the badge cannot contradict each other. An employee with nothing completed but an assessment under way reads "Assessment running" rather than "no records", and next to a completed one the tile names it first and then "+N active" - every assessment not yet completed or cancelled
- Who runs employee records - adding people, editing and moving them, their timeline, work history and pay - is the section access setting; admins and division managers unless you change it. The org structure still fences it: admins - and HR once given the section - reach everyone, anyone else the departments they head, and a new or moved person lands inside those departments. Below admin nobody edits their own record here beyond education and courses, nor an admin's or HR's record. Deleting someone and changing roles stay with admins, and the employee pickers across the product keep working whatever the setting says. Recruiters, hiring managers and employees go no further than View here - the setting shows their Manage locked with the reason
- Assigning someone as a division manager or deputy upgrades their role automatically; removing the assignment asks for confirmation before the downgrade
- The card header repeats the same issue badges the directory shows for that person, so opening a profile says what is wrong before any tab is clicked
- Each issue badge carries the date its problem is scheduled to resolve — the open plan's deadline or the open assessment's due date — so the card answers "there is a problem, when does it close?" in one line
- A Development dynamics tile reports what the last quarter changed for this person: development plans finished and the competences they raised — scored higher in an assessment completed after the plan than in the one before it
- An actions menu on the header starts anything that is about this person — a development plan, an assessment, a career event — on the screen that owns the flow, with the employee already filled in

### Employee Directory

A filterable directory of everyone in the workspace.

- Columns: name and email, division, position, specialization and grade, status
- Multi-select filters for divisions, statuses, positions, specializations, grades, and issues. Selections persist in the URL, so a filtered view can be bookmarked or shared
- An Issues column names what is wrong with each person — no active account, incomplete profile, overdue or stalled assessment, competence gap with no development plan, overdue plan, no assessment in the last six months — and the Issues filter narrows the list to one of them
- Search runs on the server and matches first name, last name, full name, email and job title across all pages
- Managers see only the divisions they manage in the filter; admins and HR see the full tree
- An edit dialog changes name, position, division, and status in one step, with the usual scope guards

### Employee Events

A timeline of milestones and changes through an employee's career.

- Event types: hire, position change, division change, termination, compensation change, certification earned, assessment complete, development plan complete, exam complete, grade change
- Events are recorded automatically on position, division, compensation, and status changes, with old and new values side by side
- Recorded events read in the viewer's language: a change shows its old and new value - name, position, division, role, pay - a hire names the position the person was hired into, and a status change is named by its title alone; text typed into a custom event is shown as written
- Filter by event type; custom events with free-text descriptions are supported

### Employment History

Two blocks on the profile cover work history inside and outside the company.

- **Current employment** tracks division and position spells in this organization. Start date is required, end date is optional, and each record shows the elapsed duration. New records prefill from the employee card
- **Previous employment** records jobs at other companies: company, position, dates, and responsibilities. Dates are validated so the start never lands after the end

### Education

Formal education records: universities, colleges, degrees.

- Institution, degree type, and field of study, with start and end dates (ongoing education supported); the degree reads in the interface language, while a degree imported as free text shows as it was written
- Degree types follow the company region: Secondary, Vocational, Bachelor, Master, PhD, Doctorate, Other by default; for Russia the levels of the Russian education system - secondary general, secondary vocational, bachelor's, specialist, master's, postgraduate - plus Candidate and Doctor of Sciences and Other. A record saved under another set keeps its value and stays selected when edited
- Everyone keeps their own education and courses current; on a colleague's card they belong to whoever runs employee records

### Courses & Certifications

Training courses and professional certifications.

- Course title, provider, completion and expiry dates, and a certificate URL for verification
- Expired certificates are highlighted in the list
- Each course can be linked to the competences it develops, picked from the same competence tree used in assessments

### Salary & Compensation

Compensation history per employee: salaries, bonuses, and allowances.

- Amounts are stored in minor units with an ISO currency code
- The type (salary, bonus, allowance) reads in the interface language in the list and in the dialogs
- Effective date plus an optional end date for time-bound records, with free-text notes
- Every change writes an employee event automatically
- Whoever runs employee records sees and edits pay - admins everyone's, division managers their own subtree's - and nobody below admin sees or sets their own. Pay changes in the timeline and in the payroll analytics follow the same rule; the person themselves still sees and is emailed their own changes
- Compensation analytics: average salary by division and totals by type

### Competence Snapshot

A snapshot of the employee's competence profile in two blocks.

- **Current position competences**: a tree of every competence the employee's position requires, with the score from the latest completed assessment at the required level. A dash renders when no assessment has reached that level yet
- **Other competences**: everything the employee was assessed on at a different level than the position requires, so results above or below the requirement stay visible
- Every row opens a per-level score breakdown from the latest completed assessment
- Score chips are color-coded against the same bar the gap label uses: green above the bar, yellow from 50% up to and including it, red below 50% — so a green chip never sits next to a gap label
- A competence scored at or below the passing bar of its assessment is labelled as a gap, in the same wording the directory and the dashboard use. The bar itself counts as a gap, and one rule decides it everywhere — the dashboard queue, the directory, this tab, the growth zones on an assessment and the campaign analytics
- A "Create development plan" action sits on the block, prefilled with the employee and the specialization and grade of their position. When the employee is already at the three-plan cap the action opens the newest active plan instead and says why

---

## Organizational Structure

### Company Profile

- Industry classification, company size, website, and description
- Company region (country), which picks regional reference lists such as the education levels on an employee card
- Company logo upload (PNG, JPEG, SVG, WebP, up to 5 MB) with drag-and-drop or import from a public URL
- Activity fields (business sectors) picked from a configurable dictionary
- The logo and profile appear on the public company page

### Section Access

- Admins choose which menu sections each role opens - none, view or manage per section and role - or hide a section from everyone; the matrix opens from the Roles page in the Admin area
- The defaults are exactly today's access, so switching the screen on changes nothing until you do
- The admin surfaces and the company profile always stay open to admins, so nobody locks themselves out; every save is logged with what changed
- Who opens data import, invitations, roles and AI settings is the section access setting too - admins by default, plus HR and division managers for invitations. Recruiters, hiring managers and employees never get invitations, and only admins edit roles - the setting shows those cells locked with the reason. Invitations follow the org structure: HR sees and sends across the workspace, a division manager only into the departments they head; who may hand out which role stays the inviter hierarchy, and changing the role of a sent invitation stays with admins

### Divisions

Hierarchical organizational units: departments, teams, offices.

- Unlimited nesting depth with an expand/collapse tree view
- Each node of the tree shows its manager and deputy, its description under the name, and how many people work in it and the departments below it - active and on leave
- A manager and a deputy manager per division; the division manager becomes the manager in its employees' 180° and 360° assessments and the default reviewer of their development plans. For the division manager themselves - or when the seat is not assigned - that is the manager of the nearest division above who is assigned; with nobody up to the top-level division, a 180° or 360° assessment has no manager participant and the plan's reviewer is the employee themselves
- List visibility follows the same scope everywhere: admins see the whole workspace, managers see their subtree, employees see their own records
- The division page shows specializations with employee counts per plate, plus an employee list with combinable filters by specialization, position, and grade. Plates cover both the specializations mapped to the division and the ones its people actually hold, mappings from the departments below it included — a child department that is mapped but not yet staffed still shows up on the parent
- Divisions with children report on their whole subtree by default — plates, filters and the employee list include nested departments, and an "Include sub-divisions" switch narrows everything back to the division itself
- An "Add employee" dialog attaches existing employees or creates new ones without leaving the page, with a confirmation step when someone is pulled from another division
- Who shapes the org chart - adding, editing and moving divisions and mapping their specializations - is the section access setting; admins and division managers unless you change it. The org structure still fences it: admins and HR reach the whole tree, anyone else the departments they head. Deleting a division stays with admins, and the division tree every other page picks from stays readable whatever the setting says

### Positions

Structured job positions linked to grades, specializations, and divisions.

- Lifecycle status per position: active, on hold, frozen, closed. Closed positions are read-only until reopened
- Headcount planning with a filled/plan indicator and a drill-down list of assigned employees. Each row surfaces the person's highest-priority alert: inactive account, incomplete profile, overdue assessment, assessment awaiting approval, or a plan awaiting review
- The position page shows the resolved competence matrix as a compact tree with required skill levels, plus a deep link to configure the matrix
- Positions can be generated with AI from a text brief, with a mandatory draft review before anything is saved
- A dedicated admin view lists employees without a position for bulk assignment
- Who authors positions - creating, editing, changing their status, approving AI drafts - is the section access setting; admins and division managers unless you change it, each position still fenced by the org structure. Generating positions with AI and the banner of drafts awaiting review are for admins and HR, since a run drafts the whole workspace's catalogue: a division manager authors by hand inside their own subtree. Deleting stays with admins, and the position pickers across the product keep working whatever the setting says
- The positions list stays readable workspace-wide through the API, so the position pickers across the product keep working; the Positions page itself is closed to a rank-and-file employee unless the access setting raises the Employee role to Manage on the company section. Where such an employee does see it, the grade, specialization, matrix and salary columns stay hidden — the page hides them rather than showing a column of dashes, and it decides from the viewer's role and the workspace switch, not from whatever rows the current page happens to hold

### Specializations

Each specialization is a full profile, not just a dictionary entry.

- List view with grade count, position count, headcount, and an Active/Inactive status matching the dictionary; detail page with Grades and Positions tabs
- Per grade: description, requirements, and a salary range in the installation currency (`BILLING_CURRENCY`, USD by default), shown to admins, HR and managers
- The competence matrix editor is a competence-by-grade table with per-cell skill levels, a heat-map tint by level, indicator tooltips, and warnings on competences that lack indicators or materials
- Matrix consistency is guaranteed: a higher grade never requires a lower level than the grade below it, both in the editor and on the server
- The grade ladder and the matrices are edited by admins and HR; the grade system behind them stays with admins
- The pointer to Settings → Dictionaries → Specializations on the list appears only for users who can manage the dictionaries
- A matrix can be generated with AI from a structured brief (responsibilities, tasks, KPIs, requirements) plus uploaded files (PDF, DOCX, XLSX, RTF, TXT). The result opens in a review screen where every suggestion can be edited or dropped before saving

### Competency Framework

The competence library: groups, competences, indicators, and learning materials.

- Hierarchical groups with two origins: built-in (system-wide) and custom (workspace-specific)
- A search over group and competence titles narrows the tree: a matching group shows with everything in it, a matching competence opens the groups above it
- Indicators per competence with skill levels and weights; learning materials with a typed format and comments
- Materials can be overridden per specialization: hide a base material for one audience or show an extra one only there. Development plans pick up these overrides automatically
- Explicit publish/unpublish workflow, plus visibility toggles per group and competence
- Custom skill levels per workspace; built-in levels stay locked
- Deactivation is guarded: an element used in a matrix, employee card, assessment, plan, or talent card cannot be silently removed, and usage checks show where anything is referenced
- Drag-and-drop reorganization of the tree with referential integrity checks
- A per-competence audit log records every publish, move, activation, and deletion with actor and timestamp
- The competence page groups indicators and materials by skill level, with editable indicator weights and drag-and-drop ordering
- Who edits the library is the section access setting; admins and HR unless you change it. Deleting from it, the skill levels and the AI generation of the tree stay with admins. Division managers read it by default; for recruiters, hiring managers and employees the Competences section is closed unless you open it, and the competence tree every assessment, vacancy and profile picks from stays readable even for a role whose Competences section is closed
- Division heads add their own competence drafts to an existing group, rename and delete them; a draft is seen only by its author, HR and admins, is offered in no picker, and joins the library once HR or an admin publishes it

### Grade System

Career progression paths built from specializations and grades.

- Grades within specializations (for example Junior, Middle, Senior) linked to competence requirements through grade chains
- A passing score per grade (75% by default) used as the reference threshold in assessments
- Grade chains feed assessment criteria, grade recommendations, and career planning

### Dictionaries

Reference data shared across the platform: specializations, grades, skill levels, material types.

- Built-in and custom entries with sort ordering and active/inactive status
- Built-in entries can be switched on or off per workspace; their titles stay fixed
- Deleting a custom entry that is referenced elsewhere is blocked with a clear message
- Who edits dictionaries is the section access setting, admins and HR by default; a role at view opens the section read-only, and every form keeps reading them whatever the setting says

---

## Recruitment

### Who Works in Hiring

- Who runs hiring - vacancies, candidates, interviews, AI analyses, consents, reports and hiring rounds - is the section access setting; admins, HR and recruiters unless you change it. Admins, HR and recruiters see every vacancy in the company — a recruiter with read access reads all of it without changing anything. A division manager or a hiring manager given Manage runs hiring in full on their own vacancies only: the division manager's department and its sub-divisions, the hiring manager's vacancies where they are named. Creating or editing a vacancy keeps it there — the Division field offers a division manager their own sub-tree, the Hiring manager field offers a hiring manager only themselves — and they add candidates from one of their vacancies; someone already a candidate elsewhere in the company is added to their vacancy by a recruiter or HR, and the duplicate warning says so. The Employee role never gets the section - the setting shows its cell locked with the reason
- Everyone else the section is open to reads the vacancies they own, are the hiring manager of, or whose division they manage - never a vacancy they applied to themselves, which stays out of their reach for good together with its candidates, interviews and scores. Hiring managers keep evaluating candidates there - scores, moving a candidate through the funnel - and read and export the interview questions, while writing them takes Manage on the section; division managers and hiring managers read the hiring rounds and fill in their own sheet on a round they are an evaluator on, as long as the section is open to them, and a vacancy's hiring manager can be named an evaluator on its rounds whatever role they hold; creating, closing and staffing rounds and inviting outside evaluators takes Manage on the section
- Recruitment settings open per tab to whoever its API admits: whoever runs hiring edits the assessment scales and reads branding and the consent templates, HR also reads data retention and the role reference, and changing any of those plus the LLM and transcription providers stays with admins; GDPR requests and the audit log with admins and HR
- The notifications that go to the hiring team when nobody else is named on them reach whoever the setting lets run hiring

### First Hiring Cycle

- A non-blocking banner walks a new workspace through the first cycle: create a vacancy, add a candidate, schedule an interview, run the AI analysis, generate a report. Steps advance automatically as the work happens
- Demo data seeds a sample vacancy with candidates and cleans itself up after 14 days

### Vacancies

- Structured vacancy fields: position, specializations, grades, division, salary, KPIs, requirements, responsibilities, conditions
- Selects cascade from the company library — position constrains specializations, specializations constrain grades — and both the competence profile and the salary range prefill from the matching grade matrix
- The salary range follows the library on every surface that edits it — create, the edit page, and the inline edit of the vacancy overview: changing position, specializations or grades refills it from the picked pairs, and a range typed by hand stands until the next such change. Pairs priced in different currencies fill nothing rather than adding up sums that do not compare
- Every vacancy has a hiring manager, defaulting to the creator; any active member of the company can be named, whatever role they hold
- Lifecycle: edit, archive with a 90-day retention window, restore, or permanently delete a draft without candidates; archived vacancies stay out of the list until "Show archived (N)" is ticked
- Status model: a vacancy starts as a draft and opens with its first candidate, or with Publish, which needs a filled Competences & indicators block. An open vacancy can be paused, closed or cancelled and a paused one reopened, closed or cancelled - each from the vacancy menu in the list and on the page, after a confirmation. Removing every candidate never sends a vacancy back to draft
- Closing records a resolution - closed with or without hiring - which has to match the funnel (with hiring needs a candidate on a hired stage, without hiring must not have one) and is shown next to the status
- A paused vacancy freezes the interview questions, interviews and manager assessments of its candidates; a closed or cancelled one is read-only as a whole, AI Insights included. The interview pages of such a vacancy are read-only too, and the API refuses the same changes
- Parallel edits are protected: a stale save is rejected instead of silently overwriting someone else's change
- Per-vacancy attachments (documents, spreadsheets, presentations, images; 25 MB each, up to 10) feed context into AI generation

### Competency Profiles

- Generate a vacancy's competence profile with AI from the description, tasks, and attachments; a clarification note passes straight into the prompt
- The review screen supports keep/drop per competence, inline edits to names, indicators, and interview questions, and shows previously saved rows as locked
- Nothing writes to the profile until the recruiter saves the reviewed selection
- Alongside the generated profile, competences can be picked straight from the company library through the same group tree the assessments use, then given the proficiency level the vacancy requires in a second step; those are the ones the internal match is scored against, and they are listed on the section with their level. Competences prefilled from the specialization × grade matrix carry the level that grade asks (the lowest one when several grades are chosen), and the talent-market card the vacancy is posted to gets the same competences with the same levels

### Candidate Pipeline

- Add candidates by hand (name plus email or phone) or by bulk resume upload: up to 50 PDF and DOCX files at once, parsed by an LLM into structured data
- Duplicate emails are caught before import with a link-or-create choice per file
- The candidate page carries contact details, the parsed resume with per-section inline editing, files, and every vacancy application with its scores
- Funnel stages ship with an 11-stage default (new through offer, offer accepted, hired, probation completed, rejected, withdrew) and can be customized per workspace or per vacancy; stage changes into a terminal state ask for confirmation, and a hired candidate can still move on to probation completed
- The vacancy's Analytics tab shows the funnel with a conversion column - the candidates who reached a stage out of those who reached the previous one, everyone counted up to the furthest stage they got to, even if rejected later - and the overall conversion: candidates on a hired stage out of all candidates of the vacancy
- The vacancy table shows last position, experience, current stage, and the two assessments side by side: how much of the vacancy profile the manager scored and how much the AI scored, each as a percentage so the two are directly comparable. The AI verdict comes with the reason for it in the row itself, not only behind a popover. The Divergence column reads "N/M" — competences where the manager and the AI disagree out of all in the profile — and its hover card lists them and links into the full-screen canvas filtered to that candidate's divergent cells
- A candidate nobody has assessed yet says so — "not assessed yet", with the reason in a tooltip — instead of an unexplained dash. Rows where the manager and the AI disagree carry a count of the competences they disagree on, and one definition of "disagree" is used everywhere: the workspace divergence threshold, applied per competence
- Candidates who already work here are marked as such wherever candidates are read — the global list, the vacancy table (with the row tinted), and the candidate page — so an internal applicant is never mistaken for an outside one

### Internal Candidates

- Before hiring outside, the vacancy offers to look inside: one action posts the requisition to the internal talent market as a vacancy card, carrying its required competences across - provided the talent market is open to the poster in the section access setting. Whoever cannot post sees no offer, only the vacancy's candidates, until a card exists
- The talent market's own competence matcher then fills the shortlist, and the vacancy shows those employees with their percentage match next to the external pipeline - the same percentage the card shows, judged against the vacancy's current competences, so a change to them shows at once. There is no second matcher and no second copy of the requirements — the card is the vacancy's twin, and the link leads to it
- Posting needs required competences picked from the company library: the AI-generated profile describes a candidate in prose, while the internal match is scored against library competences and assessment results
- The card is created as a draft, so nothing is announced to employees until someone publishes it from the talent market
- Internal matching is part of the employment relationship — it reads competence and assessment data the employer already holds for its own staffing decisions (legitimate interest), so it needs no separate employee consent. A per-vacancy switch lets the recruiter who owns a requisition keep a sensitive one out of the internal search; it is on by default and off means the vacancy cannot be posted to the talent market at all. Once the vacancy has been posted the switch is locked on — the form shows it checked and disabled with the reason, and the API refuses to turn it off — so a requisition can never display a shortlist it claims not to search for; removing its talent market card unlocks it again
- Changing a vacancy's required competences updates the card it was posted to and re-runs the match, so the internal shortlist never answers a question the requisition stopped asking. Employees added to the card by hand show the same talent-market percentage as everyone else, however they got on the list
- Everyone who can open a vacancy sees its full internal shortlist: the access scope of the requisition decides who reads the matches, not the directory scope of the person reading, so two people working the same hire never see a different list. Each name links to the employee's profile only for a viewer who may open it, and is plain text for everyone else — the list is the same for all of them, the link is not
- A shortlisted employee can be moved into the vacancy's own candidate pipeline in one click, and their profile becomes the resume: current and previous employment, education, courses and certifications, and the competences of their position are mapped onto the candidate's parsed resume. The row then links to the candidate it created instead of offering the action again, and the internal-candidate marker follows the new candidate everywhere

### Interview Questions

- Question sets per candidate and vacancy, generated from the resume and the competence profile, with manual editing throughout
- Generation runs in the background: the set shows a progress bar and a Cancel button while it is being written, and the other sets stay available meanwhile
- Questions can be added two ways: a custom question written by hand, or generated from the vacancy's competency indicators — pick competences from a searchable tree and each becomes a question carrying the competence's indicators, follow-up questions, and rationale
- Every question shows its goal, priority, and the profile competence it probes, so coverage gaps are visible at a glance
- Sets evolve across rounds: covered topics are marked (by hand or from the transcript) so the next round skips answered ground, and blind spots from prior analyses become probes
- Only the first set is written from the resume alone. A new set is created for a specific assessment round — an existing one or the next interview, opened from the dialog — and built on a completed interview, so a round can never end up with two sets or none. The generation reads the earlier transcripts, AI analyses, and unanswered blind spots, and goes deeper where the evidence was thin rather than repeating what was already answered
- The vacancy's Questions tab collects every candidate's latest set in one place, filtered by candidate and by any combination of the vacancy's competences
- PDF export in compact, full, and card layouts

### Manager Assessments

- Workspace-defined assessment scales (2–10 weighted levels); each vacancy freezes its scale on the first score. Each scale carries its own divergence threshold, readable and adjustable on the scale itself after it was created
- Assessment rounds per candidate (pre-interview, numbered interviews, final) with a separate sheet per evaluator, always listed in hiring order
- Several colleagues can score the same round: add an evaluator and they get their own sheet plus an email invitation with a direct link. Each writes only their own row, and a colleague's sheet stays hidden until you submit yours, so nobody anchors on someone else's answers. Pre-interview rounds keep a single evaluator
- Round lifecycle from the tab menu: complete, reopen, archive, restore. Completing or archiving a round freezes it — sheets turn read-only for the hiring team and for external evaluators alike, and the outstanding invitation links are revoked. Whoever reads the candidate without scoring the round — not on it, or the round is closed — sees its sheet once, however many evaluators it has: no answers marked, each competence carrying its round average with every evaluator's score in the tooltip, and the progress and average counted over all evaluators. An evaluator of a closed round sees their own answers on it, with the same round-wide averages and progress. A round can be marked complete once every Critical competence is scored by at least one evaluator, internal or external, and at least one competence is scored at all — your own sheet, started but not finished, does not lock it; the server enforces the same rule. An archived round keeps every score but drops out of the candidate's average and is marked as excluded. An evaluator who already submitted can still open their sheet and sees why it is read-only; once the round is reopened, a sheet whose invitation allows re-editing takes edits again until the link expires
- The candidate's Manager score for a vacancy comes from a single round — the last completed one in hiring order (pre-interview, interviews, final), regardless of when it was closed, falling back to the last scored round while none is complete and skipping archived rounds entirely. Both the candidate page and the vacancy table name that round in the score's tooltip
- Indicator-level and competence-level scoring with autosave and a completion marker. Every saved score, round action and revoked invitation also refreshes the Manager score shown in the candidate page's Vacancy applications block, without reloading the page. Scoring a competence's indicators derives its overall score; setting the overall by hand instead clears the indicator answers, so the two never contradict each other
- The round header carries the round's average score — the mean across every evaluator and competence, alongside its percent of scale — and shows an em dash until the first score lands. While you are still scoring the round yourself, it counts only the sheets you may already read, so the header cannot hand you a colleague's number before you submit
- Percent of scale is one number everywhere: a level is worth the weight the scale gives it, an average sits proportionally between its two neighbouring levels, and the round header, the vacancy table's % match, the assessment matrix and canvas, its Percent toggle and its export all use that one conversion, and the vacancy report workbook converts the percentages it prints with it too. On the standard 1–4 scale a 3 is 66 %, never 75 %
- Each competence shows its own cross-evaluator average with a tooltip listing every evaluator by full name with their score, headed by "Evaluators disagree" when they differ by the scale's divergence threshold or more — the icon then turns into a warning. External evaluators count toward these averages once they submit; a sheet whose invitation is revoked or declined stops counting
- External evaluators join through secure token links with expiry, no account needed. The public evaluation page shows the resume and question list next to the scoring sheet and keeps the platform itself closed off. PDF resumes render inline; Word and text resumes are shown as an extracted preview, and the file is only downloaded when the evaluator asks for it. A candidate entered by hand has no file at all — their resume is shown as its summary, experience, education and skills. A link that can no longer be used says which reason applies: declined, expired, revoked, or a candidate or vacancy that is no longer available
- The vacancy owner is emailed as soon as an external evaluator submits, with a link that opens the candidate's manager assessments on the very round that was evaluated, scrolled to the block's title with a little of the page above it still in view; corrections to an already submitted sheet do not send it again
- Recruiters track invite status (pending, opened, in progress, submitted, expired) and act on each invitation from its own menu — resend the same link, revoke it, or read the submitted evaluation in a read-only panel — revoking an invitation that was already filled in keeps that evaluation readable and marks it as no longer counted toward the round score. Resending the same invitation is throttled for a few minutes, and every invitation email counts against an hourly ceiling per recipient address, so neither a repeated click nor a stream of new invitations can flood an evaluator's inbox. Both limits are deployment-tunable
- The vacancy's Assessments tab expands into a full-screen canvas: a candidates-by-competences matrix with manager and AI scores side by side, view and round switches, divergence-only and no-score filters, a cell-details footer, per-candidate totals, and XLSX/CSV export of exactly the rows and columns left on screen

### Interviews & AI Analysis

- Schedule interviews directly from the candidate page: vacancy, assessment round, title, date and time, duration, several interviewers, recording type, and notes. New cards appear at the top of the list
- The interviewers assigned to a future interview are emailed the candidate's name, the vacancy, and the local date and time with its time zone named. Later changes follow the same slot: someone added later gets the invitation, a move tells the people already on it the new time, a dropped interviewer is told they are off it, and archiving the interview cancels it for everyone — each in the recipient's own language
- Each row links to the interview by its title and shows its round, the date it was added, its status, and a menu to edit or archive it
- Archiving hides an interview behind a "Show archived" filter and keeps it restorable for 90 days; the round link is released and the AI scores it produced are marked as coming from an archived source. After the window closes the recording is deleted and the record stays for audit
- The interview page opens on its title, the vacancy and round it belongs to, a Details block (candidate, type, status, added, date and time, duration, interviewers) and a Notes block — with inline editing where it still makes sense. Every assigned interviewer is named for everyone who opens the page, including one who has since applied to the vacancy and is no longer offered as an interviewer on it
- Upload audio (mp3, wav, m4a) and video (mp4, webm, mov, avi) up to 500 MB, or text transcripts up to 10 MB, several files at once
- A pasted transcript or an uploaded pdf/txt one is split into speaker turns: a line that opens with "Interviewer:" or "Candidate:" (or the German or Russian word for either), or, in a transcript labelled that way throughout, with a speaker's name starts a new turn. Editing the whole transcript splits it again, and the interview page shows the transcript as uploaded, with its type no longer editable
- Transcription and AI analysis can start on their own after an upload, and an uploaded pdf or txt transcript, which needs no transcription, goes straight to the analysis; the switch for it is remembered per candidate and vacancy in the recruiter's browser, so a reload keeps it as it was left
- Uploads are chunked and resumable: pause, resume, retry, and continue after a browser reload
- The interview's recording type follows the file that is uploaded; when it contradicts the type chosen at scheduling, the recruiter is asked to confirm the switch first
- Consent capture with magic-link signing runs before any upload; while a link is out and unsigned it can be sent again from the banner, after a confirmation naming when it last went out — to the candidate's current email, with the same link while it is valid so the copy already in their inbox keeps working, and a new one once it has expired
- The one AI step before consent is reading an uploaded resume when the candidate is created from it — the candidate sent that resume in. Everything after that needs the candidate's signed consent: AI Insights, interview questions, pasted or uploaded transcripts and their analysis, and interview recordings all stay off until the candidate signs, with the reason shown next to the action. Candidates already in the system who never signed are no longer sent to AI until they do
- The candidate can withdraw consent from the same link at any time; from then on AI processing and uploads are refused, an analysis still waiting in the queue is stopped (the credits charged when it was started are not returned), the candidate page says consent was withdrawn, and a new consent request can be sent. The withdrawal is recorded in the audit log
- In a demo workspace every new candidate is consented on creation, and so are the sample candidates of the recruitment onboarding walkthrough, so the AI features can be tried straight away
- Transcription through pluggable providers — Deepgram, Whisper, AssemblyAI and Yandex SpeechKit, three of them with speaker separation; the recording is transcribed in the tenant's content language, or in the language the provider detects when none is set, and every configured key joins one fallback chain, so a provider that refuses the request passes the interview to the next one instead of failing it — the workspace's own keys first, then the platform's, led by the provider the operator picks with `TRANSCRIPTION_PROVIDER_DEFAULT`; an in-app player covers audio and video with speed control and keyboard shortcuts
- Whoever runs hiring on the vacancy (admin, HR and recruiter by default) downloads the recording from the player under its file name; every click signs a fresh short-lived link, and everyone else who reads the interview only plays it back. A playback link that expired while the page stayed open is renewed when the player next needs it, so a citation clicked later still plays from its line
- The recording is prepared before it is sent out: the video track is dropped and the audio re-encoded, so an hour of interview travels as a few megabytes instead of half a gigabyte, and a recording still above a provider's request-size limit is split into overlapping parts and stitched back into one transcript
- When the provider that transcribed the interview does not separate speakers, the turns are split into interviewer and candidate from the transcript itself, so the analysis still knows whose words it is scoring
- The analysis pipeline reports data completeness, competence scores, blind spots, process findings, red flags, and a verdict
- The analysis, its questions, the generated competency profile and the candidate reports are written in the workspace's content language whatever language the interview was conducted in; a workspace that never opened the setting falls back to the language the vacancy was created in, and opening the settings page does not count as answering
- Two modes: resume-only (a fast pre-screen that never returns "recommended") and full (interview-anchored, with citations from the transcript). A prior resume-only run upgrades to full for the price difference. Resume-only reads an uploaded resume or a parsed resume entered by hand on the candidate card
- Every citation the full analysis saves is checked against the transcript: its quote must be in the segment it names, and its timecodes are that segment's own; a quote the transcript does not hold is dropped, and the run records how many were. A scored competence with nothing left to back it reads "Unconfirmed", a quote the transcript lost after an edit is marked outdated, and a text transcript shows the quote itself instead of a timecode with no recording behind it
- Progress renders stage by stage with a cancel option; resume citations click through to the matching resume section, and the quoted fragments are marked in the parsed resume and click back to their citation
- The analysis card spells out, in words, where the manager and the AI disagreed — which competence, both scores, and which way the AI leaned — or says that the two agree, or that no manager has scored the candidate yet, so the AI verdict is never the only voice on the page
- The platform flags an analysis that no longer matches its inputs — a re-parsed resume or a hand-entered one edited since, edited vacancy competences, a run past 30 days, or an interview transcript the analysis never saw — and offers the re-run that fixes it. A stale baseline also closes the discounted upgrade, so a full analysis is never built on findings that have moved
- The candidates table reports whether an analysis is running right now, derived from the data rather than from the last run
- Where a manager's scores and the AI's disagree by the workspace threshold, the candidates table counts those competences and names them on hover — including the ones scored in an assessment round or judged by a resume-only analysis — and opens the canvas filtered to exactly those cells
- Everyone the analysis concerns gets an email when it finishes or fails, naming the candidate and linking straight to the result
- Bulk analyze queues a resume-only run for every candidate that has a parsed resume but no verdict yet
- Hiring managers see reframed process findings rather than raw red flags; access is role-aware throughout

### Hiring Reports

- Consolidated XLSX reports generated in the background: a summary ranking sheet, a competence matrix of candidates against the profile, a detail sheet per candidate, and a data-completeness sheet
- The Generate dialog picks the candidate set (all active, finalists only, or a custom selection), which of the four sheets to include, and the audience
- An audience switch keeps recruiter-only findings out of the hiring manager's copy
- A report list with filters and download links valid for 24 hours
- Workspace logo branding in the top-left corner of every sheet

### Recruitment Settings

- A single settings hub for scales, AI and speech-to-text providers, branding, retention, roles, and templates
- Bring your own keys for LLM and transcription providers (Anthropic, OpenAI, Gemini, Azure, Yandex, GigaChat, Whisper, Deepgram, AssemblyAI, Yandex SpeechKit); keys are encrypted at rest and never returned in full. Whisper can also point at your own OpenAI-compatible server
- Connect your own model for recruitment from the interface: an OpenAI-compatible server such as Ollama or vLLM is added by its address, with no API key when the server needs none, and a connection check on each provider sends one short test request and says whether the model answered - or why not: unreachable server, rejected key, unknown model
- Retention windows per data type with a warning on legally short values, applied every night: once an item is older than its window, counted from the day it was created, an interview loses its recording, transcript and AI analysis, a resume its file and parsed text, a consent record the signer's email, IP address and browser (the consent itself stays on record), and a hiring report is deleted; an interview still being transcribed or analysed waits for the next night. Each run is written to the erasure log; the audit log is kept as it is. A workspace that has never opened the retention settings keeps everything until it does

### Audit & Compliance

- An append-only audit log of every mutating action with change diffs, IP, and user agent, browsable with filters
- Every stage move names who made it, in the candidate's stage history and in the log with the stage before and after; AI runs name who started them, including the transcription and analysis that run on their own after an upload, which are logged under whoever uploaded the interview
- GDPR export gathers everything about a person into one JSON document with a 7-day download link; the file itself is deleted when the link expires
- GDPR erasure replaces personal data with redaction markers across resumes, transcripts, AI analyses and the verdicts shown on the candidate card, evaluator notes, generated questions and consents; it deletes the stored files, the hiring reports that list the person and their earlier export files, and strips the person's full name, email address and phone number (matched as whole words) from the audit log, notifications and email log while the events themselves stay
- Erasure changes only the requesting company's data: a person who is also a candidate at another company, or has a user account, keeps that record, and only this company's candidate is detached from it
- GDPR export and erasure open from the candidate page (Export / delete data) and from the recruitment settings, where the GDPR page finds the candidate by name or email

---

## Assessments

### Assessment Types

- Self, 180-degree, and 360-degree assessments
- The create dialogs explain what each format is for: self-assessment is the employee's own view and suits development tracks, independence and initiative; 180° and 360° add managers, colleagues and subordinates and form the basis for personnel decisions
- Participant roles: self, manager, peer, subordinate
- Competence-based evaluation with configurable indicators and weighted answer scales

### Evaluation Criteria

What to evaluate is chosen in a dedicated panel, on single and mass assessments alike.

- Three modes: the employee's current position, a target specialization and grade, or hand-picked competences
- Target position mode pulls competences and levels from the grade ladder; "All grades" takes the highest level per competence
- Hand-picked mode opens a tree picker with group-level checkboxes and search
- The skill level per competence stays editable; on mass assessments, criteria propagate to every active child

### Answer Scales

- A default scale ships out of the box; workspaces can create their own
- The scale builder validates that percent levels cover 0–100 without gaps, orders options by drag-and-drop, and supports an optional "Don't know" answer that is excluded from scoring
- The scale is frozen into the assessment at launch, so editing a scale never changes a running assessment
- Answer options are labelled by name only; what each answer option means sits once in a collapsed legend above the questions instead of repeating under every indicator - in the survey, the question preview and the scale preview alike. A scale with no descriptions shows no legend, and an option without one reads "Not specified"

### Taking a Survey

- Surveys open in a side panel with room for full question text and per-option labels
- Every answer saves automatically; comments save on a short debounce
- Closing the panel keeps the draft, and reopening restores it, so partial progress survives navigation
- Submitting with questions left unanswered marks each of them in red and scrolls to the first one, in the order the panel shows them, with focus on it - no hunting through a long questionnaire

### Assessment Lifecycle

- Status flow: Draft → Sent → In progress → On review → Done, with Cancelled reachable from any state
- The first submitted answer moves the assessment to In progress automatically; review starts when every participant finishes, or earlier by hand once at least one participant is done
- Deadline tracking with email reminders; past dates are rejected at creation and at launch
- Sending is refused when the selected evaluation criteria resolve to zero indicators, so an assessment can never go out with an empty questionnaire
- Each employee can have at most 3 active assessments. Mass launches skip employees at the cap and report how many were created
- Started from an employee card, the assessment arrives configured: a title naming the employee, 180° when they have a line manager - the head of their division, or of the nearest division above when that seat is theirs or empty - and self-assessment when they do not, and — filled in the same transaction as the assessment itself — the "current positions" criteria plus the tenant's default rating scale. Only the deadline and Send are left. The dialog says so when the employee has no position, and creation still succeeds with the criteria left to pick by hand
- Participants get an email when the assessment goes live, when it completes, and when it is cancelled after launch
- Who runs assessments - creating single and mass assessments, sending and calibrating them, inviting external reviewers, reading the detailed results and running CPA cycles - is the section access setting; admins and division managers unless you change it. The setting opens the buttons, the org structure still says whose assessment it is: admins and HR see every assessment, a division head their own department's. Everyone the section is open to answers the assessments they take part in, and closing the section for a role closes it for the people in it. Answer scales stay with admins and HR
- The Assessments page opens in tabs: Assessments - the full list, for whoever runs the section; My assessments - the ones about you, once sent; To do (N) - the active ones where your questionnaire is still open, whatever your part in them. Everyone the page is open to gets the last two, and they show only your own, a manager's included

### Results & Calibration

- Scores aggregate per role: indicator answers average within a role, roll up to skill levels using indicator weights, then to a per-competence percent, and the final score is the mean across roles. "Don't know" answers never count
- Each competence shows a percent, a resolved level from the scale, and a per-level breakdown. Percents render as colour-coded chips — green above the passing bar, yellow from 50% up to and including it, red below — with a muted dash when there is no result
- The overall score is the mean of per-competence percents and appears next to the results once the assessment completes
- Reviewers can calibrate: override per-question totals while the assessment is locked for participants. Calibrated values are marked, survive recomputes, and can be reverted in one step. While the lock is on, participants still see their Take / Evaluate actions, greyed out with a tooltip explaining that the questionnaire is closed
- A detailed results view for reviewers shows per-role answers and comments for every indicator
- Above the results table, reviewers see the self-versus-manager gap per competence and overall, from On review onwards — so a divergence is visible before the assessment is approved
- Employees see their own results when the assessment is done; peers and subordinates never see results of assessments they only participated in

### Growth Zones & Strengths

Once an assessment is completed, its results are read as two lists before the table.

- **Growth zones**: every competence at or below the passing bar, worst first, with its percent
- **Strengths**: everything above the bar, best first
- Either block says so plainly when it is empty — all competences above the bar, or none of them
- The full results table moves behind a "Show all results" toggle: the two blocks answer what it was usually read for, the table keeps the average, percent and scale level for when the detail is wanted
- A "Create development plan" action on the growth zones builds a plan from exactly those competences — not the whole grade matrix — named after the assessment and with the materials each competence's level requires. Once such a plan exists the action becomes "Open development plan"
- The blocks and the action appear only on completed assessments: before approval the totals can still move in calibration

### Passing Score & Grade Recommendation

- A configurable passing score (default 75%) on position-based assessments, locked once the assessment leaves Draft
- On completion the platform computes a match percent per grade and recommends the highest grade that clears the threshold; if none does, it shows the closest grade marked as not confirmed
- The recommendation renders as a card with progress bars per grade, and the mass assessment summary lists the recommended grade per employee

### Mass Assessments

Run one campaign across many employees.

- Campaign-level type, scale, deadline, and criteria applied to every child assessment
- Unified tracking, per-employee recommendations, and score analytics: ranking, distribution, completed versus total
- Copy a previous round (criteria, participants, settings) and compare rounds over time

#### Campaign analytics

Once at least one child assessment is done, the campaign page adds an Analytics block built from the completed children only — cancelled and in-flight ones never move the numbers.

- **Growth zones** and **Top competences**: the ten weakest competences at or below 75%, and everything above it, averaged across the employees who have a value for each
- **Employees at risk** (below 50%) and **Top performers** (above 75%) as avatar plates that open a sheet listing each person with their division, result, and a jump to their assessment
- **Detailed results**, filtered by division, specialization, competence, and employee: an average match level gauge plus either a per-employee results table (current positions) or a competence matrix crossing competences with employees, with an average column and per-column jumps into each assessment
- On "all grades" campaigns the average shows per grade, a second matrix crosses grades with employees, and the best-matching grade is highlighted throughout
- **Summary**: the average match per grade as a bar chart, and the competence tree carrying the campaign's average result per competence

Employees answered entirely with "Don't know" stay visible in the matrices but never enter an average.

### External Reviewers

Collect feedback from people outside the system.

- Unique shareable links per reviewer, no login required, with a configurable expiry (30 days by default)
- Responses aggregate with internal participants; admins see who was invited, but individual external scores stay anonymous

---

## Development Plans

### Personal Development Plans

Structured growth plans tied to assessment results.

- At most 3 active plans per employee; the platform blocks a fourth until one finishes
- Each plan links to a development specialization and grade, prefilled from the employee's position. Plan items are then seeded from the competences that pair requires, with materials capped at the target skill level
- A plan started from an assessment's growth zones carries no development specialization or grade: its items are those competences, and the plan page names the source assessment with a link back to it instead
- Status flow: Draft → Sent → In progress → On review → Done, with Returned and Cancelled. The first item the owner ticks moves the plan to In progress automatically
- Only the plan owner ticks items off; a ticked item locks so accidental clicks cannot undo real progress. Reviewers and admins keep full control during review
- A plan cannot be sent until every item has at least one material
- The employee works the plan from their own side: materials open in a new tab (a material with neither a link nor a file says so instead of showing a title that looks clickable), items are ticked off, a comment goes on the plan, and the plan is handed back for review — the personal dashboard tile opens the active plan directly
- During review the employee sees a frozen snapshot of the items while the reviewer keeps editing live
- Past-due deadlines are highlighted in red in the list and on the plan page
- The assigned employee gets an email when the plan is sent; deadline reminders follow
- Who authors plans - creating, editing, restoring a version, drafting with AI and moving a plan through every status - is the section access setting; admins and division managers unless you change it. HR moves plans through every status as well, whatever the setting. The setting opens the buttons, the org structure still says whose plan it is: admins and HR reach every plan, a division head their own department's. Everyone the section is open to keeps their own side of their plan, and closing the section for a role closes the plans of the people in it too
- The Development page opens in tabs: Development plans - the full list, for whoever authors plans; My plans - your own, once sent; To do (N) - your plans that are sent, in progress or returned to you. A letter about your plan opens the tab that holds it, and a letter to the reviewer opens the plan itself

### Plan Items & Materials

- Items link to specific competences or stand alone
- Materials carry a title, format (course, book, article, video, practice), link or attached file, and estimated study time
- Items and materials reorder by hand; completed items become read-only until unchecked during review
- Progress recomputes whenever items are added, removed, or toggled

### Plan Comments

- Comments at the plan, item, or material level with file attachments; images render inline
- A threaded discussion between the employee and the reviewer lives next to the work itself

### Plan History & Versioning

- The platform snapshots the full plan state on every key transition: sent, review, returned, done
- Any version can be viewed or restored later

---

## Exams

### Exam Management

Knowledge testing with configurable questions and pass criteria.

- Single choice, multiple choice, and essay questions, with images, weights, and ordering
- Questions are editable while the exam is in Draft and lock at launch
- Status flow mirrors assessments: Draft → Sent → In progress → Completed, with Cancelled available until the exam terminates
- Launch validates at least one question, at least one assigned employee, and a future deadline
- Who runs the exams - writing them, assigning them, reading everyone's results - is the section access setting; admins and division managers unless you change it. An exam already assigned stays open to the person taking it whatever the setting says, so a closed section never strands an invitation
- The Exams page opens in tabs: Exams - the mass exams, for whoever runs them; My exams - your own, once sent; To do (N) - the ones still to take, which the assignment letter opens

### Assigning & Taking Exams

- Employees are assigned through a searchable picker filtered by name, email, division, or position
- The exam opens in a side panel; answers save automatically and a closed panel resumes from the draft
- The answer key is never exposed while taking the exam
- The submit button stays disabled until every question is answered; after submitting, the employee sees the earned score and a read-only review with correct answers highlighted
- When the last participant finishes, the exam completes automatically

### Pass Mark & Results

- One pass mark per exam: a minimum percent or absolute points, optionally scoped to a grade or specialization
- Automatic pass/fail per participant, with scores, timestamps, and links back to the employee profile

### Question Import

- Bulk import from Excel on the exam page while the exam is a draft, for whoever edits its questions, with a downloadable template that comes filled with example questions
- Up to 6 answer options per question, weights, and Markdown in question text
- Duplicate detection against existing questions and row-level error reporting: the page shows how many questions came in and every skipped row with its number and reason
- A file that is not a readable Excel workbook is refused as a whole

---

## Talent Market

### Talent Cards

An internal job board for open positions and project opportunities.

- Three card types, explained on the board itself and in the create dialog: **Vacancy** — an open position to fill; **Talent** — a bench for a role that is not open yet; **Project** — a time-boxed task staffed with specialists from inside the company for its start and end dates, who keep the position they already hold. The type is an organizing label: matching, statuses and appointment work the same on all three
- The board header counts the cards by type — "3 vacancies · 1 talent · 2 projects" — following the active filters
- Each card carries a start date, an optional end date, and a rich description
- Status flow: Draft → Published → Completed or Cancelled. A card publishes only when it has at least one required competence and one candidate
- Published cards freeze their requirements; edits require unpublishing

### Requirements & Matching

- **Required specializations**: rows of specialization, grade, and an optional minimum of years of experience
- **Required competences**: rows of competence and skill level. Picking a specialization prefills its competences from the grade ladder
- A match threshold per card (50–100%) controls how strict the competence matcher is
- The candidate pool fills automatically: an employee qualifies on work experience at matching positions and on assessment results for the required competences. Results from higher-level assessments project down to the required level. An assessment that was run without a target level counts against every required level of that competence
- The match cell shows competence and experience scores as separate chips plus how many required competences the employee actually clears. The whole cell opens a breakdown that names the verdict — met, or how many competences sit below the card's bar — and lists the required-versus-current numbers per row

### Candidate Pool

- Candidate statuses: matched, not matched, appointed. Manual nominees and appointed candidates survive automatic recomputes
- The status says why, not only whether. A card can gate on competences, on experience, or on both, so the row names the axis that is short — "Competencies met, no experience" once a re-assessment has closed the competence gaps but the card also asks for years the candidate does not have, or "Competencies and experience short" when neither is there. Without it a bare "not matched" next to a freshly raised percentage reads as stale data when it is in fact correct
- The match percentage and the breakdown are recomputed on every open, so a finished assessment shows up without any action; the composition of the pool — who is on the list at all — changes on an explicit Recompute
- Employees on a published card can react to express interest; their manager gets an email, and reactions break ties in the ranking
- When the person reacting is short on a vacancy's or a project's required competences — judged live, not from the stored score, and only on competences: missing years of experience alone draw no reply, since a plan cannot close them — they get an answer instead of silence: the reaction stands, they keep their place on the candidate list, and the message points at closing the gaps rather than at a rejection. From there they can ask their manager for a development plan — employees cannot create one themselves — and the manager's notification names who asks and for which card, and opens the very breakdown the plan is built from
- A development plan can be built straight from the breakdown: its items are exactly the required competences the candidate is short on, with the learning materials for each, and the plan is linked from the candidate row. Appointment and the plan are independent — a candidate can be appointed and then work the plan, or finish the plan and be appointed afterwards
- Appointment asks for confirmation, so a stray click cannot pin a candidate
- Emails go out on every lifecycle event: publish, being added to a live card, appointment, completion, cancellation, and removal from a published card
- Recruiters and hiring managers read every card, as HR does, so an internal shortlist on a vacancy opens its talent card; writing to the board still follows the section access setting
- The section is open to regular employees, narrowed to the cards their own name is on: a card they are a candidate on once it is published, plus a card of any status they have been appointed to before it goes out. They read their own row and their own match breakdown — not the shortlist they are ranked in — and every write control stays hidden
- A vacancy card can also come from recruitment: posting a requisition to the talent market creates one with the vacancy's required competences already on it (see Recruitment → Internal Candidates). Its Details name the vacancy it is based on, linked for whoever may open that vacancy in recruitment
- Who authors the board - creating, publishing, staffing and deleting cards - is the section access setting; admins and division managers unless you change it. The setting opens the buttons, the org structure still says whose card it is: admins and HR reach every card, a division head their own department's and the ones they created. Everyone the section is open to keeps the cards their own name is on, and closing the section for a role closes those too
- The Talent Market opens in tabs: Talent Market - the board, for whoever authors it; I'm a candidate - the published cards you are a candidate on and the drafts you are appointed on; I'm appointed - the cards you are appointed on, cancelled ones aside

---

## Coverage

Break a process or a project down into steps, see who covers each step - an AI agent type, a person on the team, or nobody yet - and hand the gaps to recruiting. Coverage is the first thing the screen opens on.

### Breakdowns

- Describe a process or a project in plain language - the description is required, since the steps are drafted from it; the AI drafts the ordered list of steps in two calls - one splits the description into steps, one tags every step with the capabilities it requires from a fixed catalog of seventeen
- Every step carries who answers for it (nobody, reputational, formal, regulatory), whether it produces a draft or changes the outside world, an optional reversibility, and the model's estimate of hours per run and runs per year, which you correct in place
- The first breakdown of a container applies itself: there is nothing to replace, so you land on the coverage with a number instead of on a button. A regeneration still asks, and shows the current and the proposed step lists side by side before you decide
- Long generations show a progress strip with the phase and a running clock
- The same text gives the same breakdown: a description your company broke down before - with the same model, prompt and content language - is answered from the stored result at once, for thirty days; spacing and compatibility forms of characters do not count as a different text, capitalisation does
- The list of processes and projects counts both under its title, is searched by title and filtered by type and status like every other list, and its title hint says what a process and a project are; each row names the owner with their position and status
- Edit the draft in place: rename, reorder by drag-and-drop, add or delete steps, change any capability chip; accept the whole breakdown when it matches reality
- Step attributes fold away behind a Details disclosure: who answers for the step, what it produces, and the hours estimate you can correct
- Capability chips show the model's confidence and the fragment of your description it relied on; a doubtful chip is marked as a suggestion until you confirm or remove it
- Reclassify a single step by telling the model what it really is ("this is a scripted call with the bank")
- Every field of a step is labelled, and rewording a step says what it did not do: the capabilities still describe the old text until you reclassify the step or change them by hand; accepting the step closes the hint too

### Coverage

- Per step: the executor verdict - an agent type from the built-in packs (or an agent you registered), a person whose assessments or grade profile carry the capabilities, or a gap - and the automation mode (automatable, draft then review, review required, blocked by judgement or by physical work)
- A step you added without capabilities and never classified is marked Not classified, with a hint to pick its capabilities or reclassify it - it no longer passes for a step that needs no capability; saving the capability picker empty says the step needs none
- A person's coverage comes from completed assessments against the passing score of their grade, or from the competence matrix of their position; the matched person is shown with their position
- The tab opens on two plaques: what share of this work moves to an agent, and what the work costs in hours a year and in your own money
- Under the share, one bar splits the yearly hours three ways - moves to an agent, moves to review, stays with people - and its legend repeats the same colours and the same percentages, so every number on the plaque has one denominator
- How well an agent does the work - better than a person, as well as a person, a draft a person finishes, or a person's own job - is rated per step by its weakest capability and sits on the step's row
- The money comes from the hourly rate an admin sets on the company profile (the link to it is offered to admins only), and any step can name its own rate in the hours editor - the field starts at the company's rate, a step left at it keeps following the company, and a step can carry its own rate before the company has one. The money of a process is the sum over its steps, each at its own rate, always in the company's currency; until a rate exists the plaques show hours only. What the agent itself costs is deliberately absent - the skill runs in your own tools, so we never see its usage, and the plaque says so
- Reviewing an agent's work still takes a person's time, so the hours that move to review read before and after (124 h → ≈ 62 h): by default half of a reviewed step's hours stay with the person who checks it, and the hours editor takes your own percent per step - clear it to go back to the default. The hours freed are the agent's bucket plus what review gives back
- Potential is not progress, so the plaque also says what is already done: "Agents already do 60 of 156 h/year of this work" counts the steps an agent you registered performs today - "I already use this" on a step moves its hours there. A step whose mode keeps it with a person is never counted there, so what is automated and what stays with people never add up to more than the process has. The list of processes and projects shows the same as a percent per row, taken from the last time the coverage was opened, so the list stays instant
- Three buckets - moves to an agent, moves to review, stays with people - as step lists, and as percentages of yearly hours on breakdowns of four or more steps; a step without an hours estimate is listed but not counted
- A verdict is marked preliminary while the breakdown is not accepted or rests on an unconfirmed capability
- Assign the person who does a step, and the person who checks and signs it, from your active employees. An assigned person outranks the match - an agent's included, which stays on the row as what could take the step - and closes the gap even without the capabilities, with a "No matching skills" badge naming what is missing
- A step where an agent drafts or someone answers for the result asks "Who checks?" until an accountable person is named; assignments change neither the shares nor the money
- Overrule the computed result on any step in scope, right on its row: pick another automation mode, or name the agent type that does the step - also where no single agent type covered it. The manual value is what the buckets, the shares, the money, the To do tab and the SKILL.md follow; while it is set by hand, its menu offers "Return to computed" to bring the calculated value back. An assigned person still outranks the agent. The choice names one agent type, so the company's own type stays apart from a built-in one with the same code, under its own name in the menu; a type later switched off is ignored, and one deleted takes the choice with it - either way the step reads the computed match. While a mode is set by hand and no agent type is named yet, the row keeps quiet about it - no "Nobody covers this" verdict, no quality light on an agent nobody picked
- Rows are navigable: the names of the executor, the accountable person and the backup open the employee card where the reader may open it (a colleague outside your HR scope opens as the directory card), a step title in any of the three buckets scrolls to that step's row, and an agent type opens a short description of what an agent of that type does
- The "assessed" and "expected" labels of a matched person open the match details: which of the person's competences cover the step's capabilities, the score of the latest completed assessment of each, and the passing score of their grade specialization it was held against. A match that is only expected by the grade matrix of the position says so and shows no score. The details follow the same rule as the name itself: only readers whose HR scope includes the person receive them

### To do

Everything the breakdown leaves unclosed, in two sections.

- **Nobody does this yet**: the steps no agent type and no person on the team covers, each labelled hire or agency. Pick them and open a hire need: a draft vacancy in Recruitment with the steps as its description and the closest competences pre-filled
- A single gap can also be handed over straight from its Coverage row, choosing whether to look inside the company first, hire from outside, or give the work to an agency
- Or assign a gap to someone on the team straight from the list: it leaves To do and is no longer offered for hiring
- **Work for an agent**: the steps an agent type covers where something is still missing - a registered agent, the skill file, or both. Generate the skill for one of them, or for all of them at once behind a confirmation, or register the agent you already run for that step. A step whose agent you registered stays here until its skill is written: the skill is what makes that agent do the step the way the breakdown describes it, so the instruction is worth having even for work an agent already handles
- Hiring is refused for a step of the second kind on the server, not only in the checkboxes: a stale screen must not open a vacancy for work an agent is about to take

### Access

Not every process is for the whole company - payroll, severance or compensation work often is not.

- Whoever the section access setting gives Coverage management - admins and HR unless you change it - sees and edits every process. Besides them, a process is seen by its owner and by the people assigned to its steps
- Each process is visible either to the whole company or only to the roles, positions and employees you name. A new process starts restricted, with its creator as the owner. Admins and HR see every process
- The owner edits the process - steps, AI runs, acceptance and who sees it - but does not delete it or hand it to another owner; that stays with the section's managers, so a process never depends on one person staying with the company
- An owner who has left is marked as such, and the section's managers name a new one - an archived process included
- A colleague who only reads a process sees every verdict and who is assigned to a step, but not which colleague a match found or what an assignee lacks: both come from assessments. A manager sees them for the people in their own divisions, and everyone sees their own
- Changes to the owner, the visibility and the rules are kept in the process's history
- The Coverage menu entry appears for whoever manages the section and for anyone who can see at least one process; a process you cannot see answers as if it did not exist

### Agent Skills

- For any step an agent can perform, generate a `SKILL.md` for it: the pack's skeleton filled with your company's competence indicators, the step's attributes and its acceptance point. The generation starts only after a confirmation
- Generation runs in the background with a progress strip and a running clock, so a closed tab never loses a file that was in fact written
- Preview the file, download it, or register the agent you already use for that step
- An agent setup guide on the Coverage tab answers what the per-step verdicts do not: how many agent types this work needs, which steps stand behind each, how many hours a year it takes over, whether you have registered an agent of that type and how many of its skill files are ready - largest hours first, so you start where it pays most
- Download everything at once: a zip of the ready `SKILL.md` files, one folder per skill, with a `README.md` that names the agent types, the steps behind each and the order of actions. The README is assembled from the same coverage the screen shows, without a model call, in your content language; the download is free and never starts a generation

---

### Agent registry

The registry behind the Coverage verdicts, as an API (`/api/ai-workforce/*`); a screen for it is on the roadmap. It belongs to the Coverage section: the roles the section access setting gives management run it, while everyone the section is open to asks for an agent for themselves and reads what they asked for.

- Nine built-in agent packs name what an agent type can do in catalog capabilities; a pack can be switched off for the company
- Register the agents the company actually runs - vendor, category, cost, contract renewal, data classification, security review, EU AI Act risk level - each on a pack, with capabilities added or removed for that one agent
- Assign an agent to an employee with its allowed use cases, a supervision level and an accountable owner; an employee requests an assignment, a Coverage manager approves, rejects or revokes it, and expiring assignments are listed
- The accountable owner of an assignment and the owner of a workflow are named only from active employees. A workflow owner is handed over, never cleared, and an employee who owns a workflow or is accountable for an open assignment cannot be deleted until these are handed over
- When an employee leaves, the assignments they are accountable for are suspended until a new accountable owner is named, and the active workflows they own are marked as needing a new owner; admins get one notification in the app and by email with how many of each need one. The workflow list filters by that mark, and naming an active owner clears it
- Describe multi-agent workflows step by step, and read every change in an audit feed filtered by actor, target and period

## AI Features

### Competence Generation

Generate competence structures with an LLM and review everything before it lands in the library.

- Four scopes: a whole competence base from scratch, an extension of one group, indicators for a single competence, and a competence-by-grade matrix for a specialization
- Every run starts from a confirmation dialog that shows exactly which data the model will read: specializations, divisions, company description, existing items. Each item can be excluded, and a free-text note refines the brief
- Results open in a review tree with cascade checkboxes: existing items are locked, new suggestions are editable and selectable. Nothing is saved without an explicit apply
- Refine a result with follow-up notes or regenerate from the same brief; the session history links refinements together
- Apply is idempotent, so a retried request never creates duplicates. New competences can land published or as drafts
- One active session per user; sessions survive navigation and page reloads, and a persistent banner links back to any generation in flight
- Learning materials can also be generated per skill level, with the same context controls and review step

### AI Settings

Per-workspace configuration that applies to every AI call.

- Effort tiers: fast, balanced (default), and thorough, each mapping to a model and a retry budget; a custom tier opens model, temperature, and retry controls
- Models come from a managed allow list, so only vetted models can be selected
- A content language setting (English or German) controls the language the AI generates competences, indicators, positions, learning materials, development plans, and recruitment analyses in — independent of the interface language. The workspace is only recorded as having answered once someone saves the page; reading it leaves the choice open, so a workspace that never set one keeps falling back per feature
- A company context field (up to 2000 characters) is appended to every prompt
- Supported providers: Anthropic, OpenAI, Google Gemini, YandexGPT (Yandex Foundation Models), and any OpenAI-compatible server (Ollama, vLLM, LM Studio) via a custom endpoint URL
- The provider selector offers only providers with working credentials: a platform-wide key, a workspace key (bring your own key), or a configured local endpoint — workspace credentials take priority over platform keys in every AI call
- The model list refreshes itself: a daily background sweep asks each configured provider for its current models, so newly released model versions appear without a redeploy; models a provider retires are never silently removed
- **AI processors.** The instance lists which outside AI companies tenant data may reach on
  the platform's keys (`AI_PROCESSORS_DEFAULT`; empty = all). Settings → AI shows the
  workspace the processors its data reaches; providers outside the list appear as not
  enabled, and a pinned model of such a provider is replaced by a same-tier model of an
  allowed one. The workspace's own keys are never restricted.

---

## Platform

### Authentication & Security

- Email and password registration with email verification; self-hosted installs get a self-serve registration page that creates the workspace and admin account
- JWT access tokens (30 minutes) with refresh tokens (7 days), single-use password reset links by email (an address with accounts in several organizations gets one link that sets the password for all of them; sign-in then asks which organization to open), and rate-limited verification resend without email enumeration
- Installations without an email provider still work: accounts verify automatically at registration
- Invitation sign-ups skip verification, since the invitation itself proves ownership of the address

### Roles & Access Control

- Built-in roles: **Admin** (full access), **HR** (people operations across the workspace), **Manager** (team assessments, plans, and data), **Recruiter** and **Hiring manager** (hiring), **Employee** (own profile and assigned tasks)
- Every account carries a role — **Employee** is the baseline nobody drops below — and an admin changes a colleague's role from their card; the role is shown in the employee list and can be filtered on
- Guard rails on the change: you cannot change your own role, demote the last administrator of the workspace, or take **Manager** away from someone who still leads a division. Each change is recorded on the employee's timeline
- Who may invite whom follows the same ladder: admins invite any role, HR everything below admin, managers only employees
- The same scope rules apply across every list in the product: admins see the workspace, managers see their subtree, employees see their own records
- The sidebar only offers what the role can actually open: hiring stays out of a rank-and-file employee's menu, and the controls on the company page appear for the roles the API accepts
- A rank-and-file employee keeps the company overview only: the Profile, Positions and Specializations tabs are not shown to them, a direct link returns them to the dashboard with an error, and the API refuses the data behind those tabs. Raising the Employee role to Manage on the company section in the access setting hands the tabs back
- A read-only **Roles** page in the Admin area lists every role of the workspace with what it can actually do and how many people hold it — the descriptions follow the gates the product enforces. The count opens the employee list filtered by that role
- The Admin area (dictionaries, invitations, data import, roles, AI settings) follows the section access setting - admins by default, plus HR for dictionaries and HR and division managers for invitations: the sidebar group shows only the entries open to the role, and opening a closed one directly shows an error and returns the user to the dashboard
- Every action in the Admin area is gated the same way on the API, so a hidden section is never merely hidden (reference data stays readable across the product, as the rest of the app depends on it)
- Reading is scoped as tightly as writing: hiring data (candidates, resumes, interviews, reports) is reserved for the roles that do hiring, and the sections under an employee card — competences, timeline, education, employment history, compensation — open only for the person themselves, their division manager, and admins
- Everyone can still look a colleague up: the employee list is a company directory for rank-and-file staff, showing name, job title, department, specialization and whether the colleague is active or on leave, with no other HR data attached. People who have left are not listed, and the directory filters by those two statuses. Grades appear there only if the workspace switches them on
- A division manager's employee list covers the whole company: their own department and its sub-departments in full, with the row actions, and everyone else as the directory shows them — no actions, and the colleague's card opens in the directory view. Filtering by role, grade, a missing position or a development problem keeps the list to their own departments, since those are the fields the directory withholds
- The positions catalogue answers to the same switch: a rank-and-file employee browses positions, divisions and headcounts, but a position's grade and specialization arrive only when the workspace has switched grades on — otherwise the directory and the catalogue together would rebuild the grade the directory withholds. Filtering by grade or specialization is closed for them too, since a filter answers the same question the column would. A colleague's own specialization is directory data and shows in the employee list whatever the switch says; the switch governs the position's attributes in the catalogue and its drill-down
- Recruiters and hiring managers always see a position's grade and specialization: a requisition cannot be raised without them
- Salary ranges are a separate line and a shorter one: positions and specialization grades show them to admins, HR and managers only — not to recruiters, and not to anyone else whatever the grade switch says
- The same holds wherever else a list of people appears — the employees on a position or a specialization, and the headcount drill-down: colleagues see the directory columns there too, not hire dates or HR alerts, and people who have left are not listed — nor does their card open in the directory view
- "My profile" in the header menu and on the dashboard opens the person's own card in full — the directory view is only what colleagues see of each other. With the Employees section closed for the role, neither is shown
- An employee's name is a link to their card wherever it appears - the dashboard, the employee list, the company tree and division pages, assessments, development plans, exam results, process rows, the talent market and a vacancy's internal candidates - exactly when the reader may open that card: admins and HR always; anyone else while the person is active or on leave, and a division manager also for people who left their own departments. Every other name is plain text, and its card does not open by typing the link either. With the Employees section closed for a role, every name is plain text, the card does not open and the global search lists no employees
- Inside hiring, a division manager sees their own department, at read and manage access alike: a vacancy opens for them when it belongs to a division they manage or names them as its hiring manager — and candidates, resumes, interviews and reports inherit that same boundary. Admins, HR and recruiters keep the whole workspace
- Writing follows the same boundary as reading: a division manager creates and edits assessments and development plans for their own people, publishes and staffs their own department's talent cards, and sees analytics and assessment exports that cover their subtree rather than the company
- The shared catalogues — competences, indicators, materials, answer scales, and a specialization's grade ladder and matrices — are workspace-wide, so editing them belongs to admins and HR. Everyone else keeps reading and using them; positions are the exception, staying with the division manager for their own subtree

### Product Feedback

- A "?" button in the app header opens a short form: rate the product with a thumb up or down and leave a suggestion, in the user's interface language
- Nothing is stored in the workspace — the submission is forwarded to the operator's notification channel when one is configured, and simply accepted when it is not

### Multi-Tenancy

- Complete data isolation between organizations; self-hosted mode runs a single workspace
- One email can belong to several organizations: login shows an organization picker, and a header switcher changes workspaces without re-entering the password

### File Storage

- S3-compatible storage (MinIO, Cloudflare R2, AWS S3) with tenant-isolated paths and presigned URLs
- Used for avatars, logos, plan attachments, and exam question images

### Interface

- Full dark mode: light, dark, or system preference, persisted across sessions
- Responsive layout tested on phone, tablet, and desktop sizes
- Global search on Cmd+K / Ctrl+K across employees (by name, email or job title), assessments, vacancies and candidates; it searches everything you can see, not one loaded page, and a division manager finds colleagues outside their own divisions
- Every section reachable from the sidebar carries a question mark next to its page heading explaining what the section is for and what belongs in it
- Interface languages: English and German ship with the product; the deployment configures the offered languages, the onboarding wizard records the workspace default, and every member can pick a personal language in their profile or the header language switcher; the wizard also sets the AI content language separately
- Backend error messages follow the interface language too, and every error carries a stable machine-readable code; adding a community language is a translation-catalog pull request — see the contributing guide
- Outbound email arrives in the recipient's language — their personal preference, else the workspace default — for both built-in templates and database notification templates, falling back to English where a translation is missing
- Built-in reference data follows the interface language too: shipped grades, specializations, competence types, skill levels, assessment statuses and types, the default answer scale, and the Standard 1-4 hiring scale - its name, description and levels in the scale settings and on internal and external evaluation sheets - translate with the UI, while entries your team creates always display exactly as typed. Where the catalog carries a translation, this holds on every screen that names a shipped grade or skill level — the employee list and card, positions and grade ladders, development plans, assessment criteria and grade recommendations, the talent market, salary analytics and global search — including the screens that only carry the name of the level or grade rather than the record itself
- Enum-valued fields — employee event types, development-plan material formats — show a translated label while the stored value stays the code, and a value the catalog does not know still renders as it is rather than disappearing

### Waitlist

- A public signup endpoint for collecting interest before launch or during a private beta, idempotent by email and rate-limited
- Captures the interest type (self-hosted, cloud, or both), role, and company, and sends a branded confirmation email

### Self-Hosted Deployment

- Docker Compose deployment with PostgreSQL, Redis, MinIO, and Caddy for automatic SSL
- White-label branding: installation name, logos, accent color, and favicon set through environment variables, for the web UI and outgoing emails alike
- Theme presets: switch the whole UI (surfaces, accent, charts, sidebar, corner radius, light and dark mode) to a curated look with one variable
- Custom sign-in background: a solid color or a full-bleed cover image on the login and registration pages
- See the [Self-Hosted Guide](/docs/self-hosted) for the full walkthrough

---

## Public API

### REST API (v1)

Programmatic access for integrations and automation.

- API key authentication, generated per workspace in settings
- All endpoints live under `/v1/` with a rate limit of 60 requests per minute per key and validated pagination
- Read endpoints for employees, assessments, divisions, specializations, grades, and reference dictionaries
- Reference dictionaries are read by type — an unknown type is rejected with a `400` that lists the accepted types, so a typo in an integration fails loudly instead of returning an empty page
- Errors the API raises carry a stable top-level `code` and a human-readable `detail`; `detail` is a plain message everywhere except the unknown dictionary type, where it is an object whose `valid_types` lists the accepted types. Two framework responses have no `code`: a `422` validation error, whose `detail` is a list of `loc` / `msg` / `type` objects, and a `429` over the rate limit, whose body is `{"error": "Rate limit exceeded: ..."}`. The OpenAPI specification describes all of it
- Batch operations create or update up to 100 resources per call — employees, divisions, specializations, grades, assessments, and exams — with per-item error reporting and partial success
- An OpenAPI specification at `/v1/openapi.json` works with any API client or code generator

---

## Monitoring & Observability

For teams running HRPulsar on their own infrastructure.

- A Prometheus metrics endpoint with request counts, latency histograms, and in-progress gauges, with path normalization to keep label cardinality under control
- Structured JSON logs with a request ID on every entry and an `X-Request-ID` response header for correlation
- Optional Sentry error tracking for backend and frontend, with personal data stripped from events before they leave the server
- Health endpoints for load balancers and Kubernetes: a full check covering the database, Redis, and S3, plus a lightweight readiness probe

---

## Onboarding Wizard

A first-login wizard for newly registered organizations.

- Shows automatically while the workspace has no employees and setup is not finished; skippable on every step
- Four steps: company info, first divisions, team invitations, and a look at the built-in competence library
- The invitation step asks for a name next to each address (invitations require one) and reports exactly which invitations went out and which failed, instead of moving on silently

---

## User Invitations

- Invite colleagues by email with a pre-assigned role, division, and position; accepting creates the user account and the employee card in one step
- Invitation links expire after 7 days; an inviter can never grant a role above their own
- Bulk invite up to 100 people at once; the response lists every address that could not be invited together with the reason
- A management page tracks all invitations with status filters (pending, accepted, cancelled, expired), resend and cancel actions, and inline editing of pending invites; the page and the registry API behind it follow the section access setting, and below admin they show the caller's own departments. Re-addressing an invitation counts as sending it, so a pending invite is edited only by someone who could have sent it
- Changing the email on a pending invite issues a fresh link, resets the expiry, and disables the old link
- The accept page introduces itself from the invitation: the invited address is shown read-only and the name entered by the inviter is split into first and last name, both still editable

---

## Notifications

### In-App Notifications

- A bell icon with an unread count and a notification list
- Covers assessments, development plans, exams, and approaching deadlines
- Mark as read individually or in bulk

### Real-Time Updates

- A single WebSocket connection per user pushes new notifications, AI generation status changes, and background task updates without a page refresh
- Polling backs up the socket, so a dropped connection never strands the interface on a stale state

### Email Notifications

- Branded HTML templates, white-label ready, with a responsive layout
- Templates cover verification, password reset, invitations, assessments, plans, exams, certificate expiry, deadline reminders, external reviews, and the talent market's below-the-bar reply and development-plan requests
- Delivery through the Resend API (cloud) or SMTP (self-hosted), sent in the background so the interface never waits on mail

### Email Delivery Tracking

- Every outbound email is logged with its status: sent, delivered, bounced, complained, failed
- Automatic retries on failure and a webhook for real-time delivery updates
- Admins can browse the log with status and recipient filters

### Notification Preferences

- Per-user settings by event type and channel (email and in-app independently)
- Everything is on by default; disabled channels are skipped silently

---

## Analytics & Dashboards

- A management dashboard built around the development loop — assess, find gaps, develop, close: four clickable stages show assessment coverage, employees scoring below their grade bar, open development plans, and plans finished in the chosen period — 30, 90 or 365 days — with how many of them met their deadline
- An action queue that turns detected problems into next steps: employees below the bar with no development plan, overdue plans, plans sitting in review for two weeks without a move (counted per plan, their owners named), and falling assessment coverage — each row deep-links into the module that fixes it
- Every tile and queue row opens the list already filtered to the people it counted, so the number on the dashboard and the rows on the page always match; the names listed under a finding link straight to the person's card
- Queue rows name the worst cases first: the people under a finding are ranked by how bad the problem is — how many competences sit below the bar and how far, how long a plan is overdue or stuck, how long since the last assessment; for a gap with no plan, people who never had one come first, then those whose last plan was closed or cancelled longest ago — and the employee list the row opens keeps the same order, with an explicit fallback to the newest-first ordering
- The employee list's Problems filter also takes three profile problems the badges show — profile incomplete, plan awaiting review, assessment overdue — matching exactly the people carrying that badge and ranked oldest first: added longest ago, in review longest, missed its end date earliest
- The gaps stage only turns red when nobody is working on the gap — gaps that already have an open development plan read as amber, and a red chip on the tile counts the ones still without a plan
- The assessed stage carries a red chip counting the people with no recent assessment, and the matching queue row's button names the same number, so "nobody assessed them" reads as a task rather than a statistic
- Every stage of the loop, the action queue and the assessment-cycle card carry a question mark that explains exactly what the number counts, including the time windows and the passing bar behind it
- A development-dynamics tile on both dashboards counts plans completed over a period the reader picks — 30, 90 or 365 days — and the competences those plans raised: scored higher in an assessment completed after the plan than in the one before it. The tile, like Completed, opens the plans finished in that period
- Dashboard figures follow the reader's scope: a division manager sees their own subtree, not the whole company
- A personal dashboard for employees: my loop stages (latest assessment, my gaps, my active plan, confirmed closures), a personal to-do queue (pending surveys, returned or overdue plans, gaps without a plan), strengths with rare-skill highlights, growth direction to the next grade, and an assessment-score sparkline
- An on-demand AI summary of the loop state — one click explains what is going on and what to do first; employees get a coach-style personal summary on their own dashboard (cached per data state)
- HR metrics over a chosen period — 30, 90 or 365 days — shown as "was → now": plans closed, people at risk, grade changes, turnover (people on leave count as employed, not as leavers), time between grade changes, talent-market match and engagement. Each metric states how solid it is: the ones reconstructed from data that gets rewritten are marked as estimates and explain their formula, and metrics this workspace has no signal for are named rather than quietly left out, each with a hint saying what it needs to appear
- Who opens Analytics is the section access setting - admins, HR and division managers unless you change it. Read access shows the charts; management adds the assessment exports and the AI summary of the loop. The level opens the page, it does not widen the figures: admins and HR see the workspace, a division head sees their own department - the division headcount matrix included. Salary figures keep the audience they have on an employee's card, admins and the person's own division head
- Active assessments at a glance: how many are being prepared, sent, in progress and on review, with the share already launched; the button opens the assessment list filtered to those same statuses
- Reports: assessment score distributions, competence heatmaps, and division comparisons
- Assessment export to XLSX, generated in the background with a download link when ready
- Long-running operations (imports, exports, AI generation) report their status through a single task-tracking mechanism

---

## Data Import

- Bulk employee import from Excel or CSV (comma- or semicolon-separated, UTF-8 or the Windows code page a Western or Russian Excel saves in, dates as YYYY-MM-DD or DD.MM.YYYY): email, name, position, hire date, work experience, education, courses
- Before importing, the preview shows every row of the file - CSV or XLSX - as the import will read it, with the reason each refused row will be skipped; the CSV template opens in separate columns in Excel whatever its locale
- Every imported employee gets an email with a link to set their own password — no shared default password. The link works once, expires after 7 days and confirms the address; until the person sets a password, an admin can resend it from the employee card, which voids the previous link. On a self-hosted installation without an email provider, the link is written to the server log instead
- Dictionary import: specializations, grades, skill levels
- Drag-and-drop upload, validation with row-level errors, and background processing with progress tracking
