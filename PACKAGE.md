# Filez4Eva

⚠️ DISCLAIMER: This is a hobby/personal project. Not a commercial product. Not for production use.

## Shift scans, photos, and other files into structured folders for permanent safekeeping

Filez4Eva is a command-line tool that helps you organize files by naming them correctly and placing them in the right directory structure. It's especially useful for managing account documents, scanned files, photos, and other personal records. Each destination ("cabinet") has its own naming pattern, whose placeholders are the data fields you (or an AI model) fill in for each file.

## Installation

It's best to install using `pipx`:

```bash
pipx install filez4eva
```

If you don't have pipx installed, visit [the pipx site](https://pypa.github.io/pipx/) for installation instructions.

## Usage

### The five commands

Filez4Eva works in stages, one command for each:

| Command | What it does | Prompts? |
|---------|--------------|----------|
| [`ingest`](#ingesting-files) | Moves files into the intake under a time-stamped name, each with an `X.yml` sidecar | No |
| [`transcribe`](#transcribing-files) | Transcribes each document to Markdown, `X.md`, with an AI model | No |
| [`classify`](#classifying-files) | Has an AI model propose a value for each field of the document's cabinet that isn't [given](#given-data), for each document | Only for a document's cabinet, with several cabinets and no `-c` |
| [`review`](#reviewing-files) | Shows each proposed record, to confirm, update or redo with another cabinet | Yes, unless every value is [given](#given-data) |
| [`stow`](#stowing-files) | Moves each confirmed document and its transcript into its cabinet, named by the cabinet's pattern | For documents not yet reviewed, unless every value is [given](#given-data) |

The main use case is two commands:

```bash
filez4eva classify -c NAME ~/Scans   # unattended: ingest, transcribe and classify every file for cabinet NAME
filez4eva stow                       # interactive: confirm or update each record, then stow it
```

**The cabinet comes first, and you choose it.** A document's
[cabinet](#cabinets) is chosen before it is classified, so the model fills
in that cabinet's fields; the model never picks the cabinet. With a single
cabinet configured, it is used without asking. With several cabinets and no
`-c NAME` (`--cabinet NAME`), `classify` prompts `Cabinet:` for each
document, so to run it unattended give `-c`:
`filez4eva classify -c NAME ~/Scans`. See
[How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen).

How the stages fit together:

- **The intake** is the holding area where documents wait between stages: a
  directory, `~/.filez4eva/intake` unless you set the `intake:` key in the
  [configuration](#intake). `ingest` moves files into it and renames them.
- **A path means new files.** For `transcribe`, `classify`, `review` and
  `stow` (the stage commands), a path (a file, or a directory, top level
  only) names new files, which are ingested first. With no path, they work
  on the documents already in the intake, and `--ingested NAME` picks some
  of those. See [Which documents, in what order](#which-documents-in-what-order).
- **Earlier stages run as needed.** Each command runs any earlier stage a
  document hasn't had yet, so `filez4eva stow ~/Scans` alone ingests,
  transcribes, classifies, reviews and stows every file in `~/Scans`.
  Transcription is done for every document first, in one batch; the later
  stages then go one document at a time.
- **The `X.yml` sidecar** next to each document `X` in the intake records
  the result of each stage under `results.<stage>` (see
  [The X.yml sidecar](#the-xyml-sidecar)). A stage that's already recorded
  isn't run again, so you can stop at any point and carry on later. Once a
  document is stowed, its sidecar moves to `<intake>/archive/`.
- **`--only`** makes `transcribe`, `classify`, `review` or `stow` act only on
  documents that have had every earlier stage, and skip the rest with a note
  on stderr, instead of running the missing stages. For example,
  `filez4eva review --ingested X` followed by `filez4eva stow --only` stows
  just the reviewed documents without any prompts, leaving the others as
  they are.
- **`--cabinet NAME` (`-c NAME`)** on `classify`, `review` or `stow` gives
  the cabinet of every document in the run that has none saved yet; see
  [How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen).
- **Given data:** `--date`, `--field NAME=VALUE` and a record on stdin give
  values for every document in the run (a file, a directory, the intake or
  `--ingested`); classification fills in only the rest, and with every
  value given there is no model call and no review. See
  [Given data](#given-data).

### Which documents, in what order

This applies to the stage commands, `transcribe`, `classify`, `review` and
`stow`. (`ingest` always takes a path; see [Ingesting Files](#ingesting-files).)

Which documents a run works on:

- **A path (a file, or a directory):** those files only, which are new
  files. In a directory, the new files are the non-hidden regular files at
  its top level, in name order; subdirectories, hidden files (names
  starting with `.`) and symbolic links are left alone. They are all
  ingested, then all transcribed, then each one goes through the later
  stages (see below). No document already in the intake is touched.
- **A path in the intake** (the intake itself, a file in it, or anything
  under it, such as `archive/`, also through a symbolic link or `..`) is an
  error before anything moves. The message points to `--ingested`.
- **No path:** the documents already in the intake, that is, the files
  there with an `X.yml` [sidecar](#the-xyml-sidecar) (`X.yml` and the
  transcript `X.md` belong to `X` and are not documents themselves).
  Nothing is ingested: a file in the intake with no sidecar (one dropped in
  by hand) is left alone, with a note on stderr
  (`Not ingested: FILE (left alone; filez4eva ingest INTAKE ingests it)`).
  Subdirectories of the intake, such as `archive/`, are never touched.
- **`--ingested NAME`** (repeatable): just those documents, where NAME is
  the document's file name in the intake (e.g. `20261025-140307-042.pdf`)
  or a path to it. They are taken in the order given; a name given twice
  counts once. Other documents in the intake aren't touched, not even for
  transcription. A NAME that isn't a document ingested in the intake, or
  `--ingested` together with a path, is an error before anything moves.

The order of work:

1. **Ingest** (path runs only): every new file is moved into the intake.
2. **Transcribe, in one batch:** every selected document that still needs
   a transcript is transcribed before any later stage starts on any
   document. For `transcribe`, that's the whole run.
3. **One document at a time:** for `classify`, `review` and `stow`, each
   document then goes through its remaining stages, from classify up to the
   command's stage, before the next document starts. Before a document is
   classified, its cabinet is chosen (prompting for it if needed; see
   [How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen)).
   With `stow`, file 1 is classified, reviewed and stowed, then file 2 is
   classified, reviewed and stowed, and so on.

With no path, the most advanced documents come first in step 3: those
already reviewed, then those classified, then those only transcribed, in
name order within each group. So `filez4eva stow` first stows the documents
already reviewed, then reviews and stows the classified ones, then
classifies, reviews and stows the rest. With a path, the order is name
order; with `--ingested`, the order given.

If there is nothing to do (no documents, or every one already has the
command's stage), the command says so on stderr and exits 0, e.g.
`Nothing to classify (2 files already classified)`,
`Nothing to stow: the intake is empty` or
`Nothing to review: no files in /home/me/Scans`.

A document that fails at any stage is reported on stderr and drops out of
the run, which carries on with the others; quitting at review ends the run.
Under `--only`, nothing is ingested, and `classify`, `review` and `stow`
transcribe nothing: a file or document that lacks an earlier stage is
skipped with a note.

`filez4eva --help` lists the commands, and `filez4eva COMMAND --help`
describes one. Running `filez4eva` with no command is an error. The older
`stow-file`, `scan-dir` and `process` commands have been removed: see
[Migrating from stow-file, scan-dir and process](#migrating-from-stow-file-scan-dir-and-process).

### Ingesting Files

To move a file into the intake, the holding area where documents wait to be
processed:

```bash
filez4eva ingest ~/Desktop/Report.DOCX.pdf
```

The file is moved into the [intake directory](#intake) and renamed after the
current local time as `YYYYMMDD-HHMMSS-mmm` (`mmm` is milliseconds), followed
by its original extensions in lower case. The new path is printed on stdout
(status `Ingested` on stderr). For example, at 14:03:07.042:

| Original name       | Name in the intake             |
|---------------------|--------------------------------|
| `Report.DOCX.pdf`   | `20261025-140307-042.docx.pdf` |
| `Scan 10.14.03.pdf` | `20261025-140307-042.pdf`      |
| `README`            | `20261025-140307-042`          |

- Extensions are the trailing suffixes that are 1-5 letters or digits and
  contain at least one letter, so `.03` and `.123` are not extensions, and
  nor is anything before them.
- Each document gets a stamp that no other file in the intake uses. A stamp
  is taken if any file in the intake is named `<stamp>` or starts with
  `<stamp>.` (another document, its `X.yml` sidecar or its `X.md`
  transcript). If it's taken, the next millisecond is used, until a free
  stamp is found. So ingesting `notes` and `notes.md` together gives
  `20261025-140307-042` and `20261025-140307-043.md`, and a later
  transcript of the first can never land on the second. A name whose
  sidecar is in the intake's `archive/` (a document stowed earlier) is
  passed over in the same way. An existing file is never overwritten.
- This also holds when several `ingest` runs into the same intake overlap on
  one machine: each run locks the intake while it checks and claims a
  stamp, so documents from different runs never share one. The lock is
  held only for that moment, not for the whole run, and no lock file is
  left in the intake. It doesn't cover runs on different machines sharing a
  network intake.
- `ingest` writes a [sidecar](#the-xyml-sidecar), `X.yml`, next to the
  ingested file `X`, recording when it was ingested, its original name and
  any source metadata.

Source metadata can be given with a repeatable `--meta KEY=VALUE` (or
`-m KEY=VALUE`) and as a YAML mapping on stdin. Both go into
`results.ingest.source`; a `--meta` value wins over the same key from
stdin:

```bash
printf 'from: email\nsubject: Your bill\n' \
  | filez4eva ingest --meta via=scanner ~/Desktop/bill.pdf
```

- Values from stdin are read as plain text, so `0123` stays `0123`.
- Stdin that is empty, isn't valid YAML, or isn't a mapping is ignored.
- A `--meta` value without `=`, or with an empty key, is an error and
  nothing is moved.

To ingest every file in a directory:

```bash
filez4eva ingest ~/Desktop/scans
```

- Only non-hidden regular files at the top level are ingested, in name
  order. Subdirectories, hidden files (names starting with `.`) and symbolic
  links are left alone.
- The same source metadata (flags and stdin) is recorded for every file.
- The status on stderr counts the files, e.g.
  `Ingested 2 files | Already ingested 1 file`.

A document already in the intake, a file `X` with `X.yml` next to it, is
left alone: it isn't renamed or given a second sidecar. Its sidecar, and its
transcript `X.md` if there is one, are left alone too. Given as the argument,
such a file gives the status `Already ingested`, which is not an error, and
nothing on stdout. So running `ingest` on the intake directory itself only
picks up files that were dropped into it by hand. This pairing only counts
in the intake: elsewhere, `X` and `X.yml` are two ordinary files, and both
are ingested.

If a file can't be ingested, it stays where it was and nothing is left in
the intake for it. In a directory run, the error is reported on stderr and
the run carries on with the next file; at the end the paths that were
ingested are printed and `ingest` exits non-zero. Ingesting a single file
that fails also exits non-zero.

### Transcribing Files

To transcribe a file to Markdown using an AI model:

```bash
filez4eva transcribe ~/Desktop/scan.pdf
```

`transcribe` works on documents in the [intake](#intake). A file given as
the path is new: it is [ingested](#ingesting-files) first (moved into the
intake and renamed), then transcribed. The transcript `X.md` (the full name plus `.md`)
is written in the intake next to the document `X`, its path is printed on
stdout, and the result is recorded under `results.transcribe` in the
document's [sidecar](#the-xyml-sidecar). The status on stderr counts the
files, e.g. `Ingested 1 file | Transcribed 1 file`. The transcript looks
like:

```markdown
---
source: 20261025-140307-042.pdf
sha256: 3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b
model: claude-opus-4-6
transcribed: '2026-10-25T21:03:12+00:00'
---
<!-- Generated by an AI process from a binary file. ... -->

...Markdown transcription...
```

The path can be a file, a directory, or left out:

```bash
filez4eva transcribe ~/Desktop/scans   # every new file in the directory
filez4eva transcribe                   # every document in the intake
filez4eva transcribe --ingested 20261025-140307-042.pdf
                                       # just that document in the intake
```

`transcribe` works out whether the path is a file or a directory. See
[Which documents, in what order](#which-documents-in-what-order): a path
means new files only, and a path in the intake is an error; with no path,
nothing is ingested and a file in the intake without a sidecar is left
alone. Files are handled in name order (or the `--ingested` order), from a
list taken before anything moves.

Other rules:

- A document that already has `results.transcribe` isn't transcribed again
  (counted in the status as `Already transcribed 1 file`, nothing on
  stdout). If every document has it, the status is
  `Nothing to transcribe (1 file already transcribed)`. There is no option
  to transcribe it again.
- If `X.md` already exists and its `sha256` matches the file, nothing is
  sent to the model: the existing transcript is used and recorded in
  `results.transcribe`.
- `--only` transcribes only documents that are already ingested, so with a
  path (new files) it transcribes nothing: each file is left where it is,
  with a note on stderr (`Skipped FILE: not ingested yet`), and counted in
  the status as `Skipped 1 file (not ingested)`.
- Supported file types are PDF, PNG, JPEG, GIF, WebP, plain text, Markdown
  and CSV.
- If a file fails (e.g. an unsupported file type, an API error, or a sidecar
  that can't be read), the error is reported on stderr, with the file's new
  name if it was ingested, and the run carries on with the next file. Its
  sidecar gets no `results.transcribe` and any existing transcript is left
  as it was, so a later run tries it again. At the end, the transcripts
  that were written are printed and `transcribe` exits non-zero. This also
  applies to a single file.
- A path that doesn't exist is an error.

See [Transcription settings](#transcription-settings) for the model and API
key.

### Classifying Files

To have an AI model classify documents so they can be filed:

```bash
filez4eva classify -c NAME ~/Scans
```

`classify` works on documents in the [intake](#intake), selected as in
[Which documents, in what order](#which-documents-in-what-order): the new
files given as the path, the documents already in the intake (no path), or
the ones named with `--ingested`. New files are
[ingested](#ingesting-files), and every document that needs it is
[transcribed](#transcribing-files), all before the first one is classified.
So after `filez4eva classify -c NAME ~/Scans` every file that was in
`~/Scans` is in the intake with its transcript `X.md` and its sidecar
`X.yml`, and the documents already in the intake are left as they were.

Each document's [cabinet](#cabinets) is chosen just before it is
classified, and saved as `results.given` in its sidecar; the model never
picks it. It is the cabinet already saved for the document, otherwise
`--cabinet NAME` (or `-c NAME`), otherwise the only cabinet when just one is
configured. **With several cabinets and no `-c`, `classify` prompts
`Cabinet:` for each document**, before classifying it (see
[How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen)).
So to start `classify` and walk away, give the cabinet:
`filez4eva classify -c NAME ~/Scans`. With `-c`, or a single cabinet,
`classify` never prompts.

Values you already know for every document in the run can be given too,
with `--date`, `--field NAME=VALUE` or a record on stdin (see
[Given data](#given-data)): e.g.
`filez4eva classify -c accounts -d 20240213 ~/Scans`. They are saved with
each document (`results.given.data`), and the model is asked only for the
other fields. With the cabinet and every field given, nothing is asked of
the model: the record is saved as reviewed (`results.review`, with
`input: true`).

The model is given the transcript, along with the file's original name and
source (`results.ingest.original-name` and `results.ingest.source`). The
result is recorded under `results.classify` in the document's
[sidecar](#the-xyml-sidecar):

```yaml
results:
  ingest: ...
  transcribe: ...
  given:
    at: '2026-10-25T14:03:08-07:00'
    cabinet: accounts
  classify:
    at: '2026-10-25T14:03:09-07:00'
    model: claude-haiku-4-5
    doctype: receipt
    summary: Amazon.ca order receipt for a USB hub
    data:
      account: amazon
      date: '20261002'
      title: usb-hub-receipt
```

- `given.cabinet` is the [cabinet](#cabinets) the document is classified
  for, saved before the model is asked (see above). `given.data`, if
  present, holds the [given](#given-data) field values.
- `data` holds a value for each of the cabinet's [fields](#fields), in
  pattern order (here the pattern is `{account}/{date}-{title}`): the given
  values as they are, and the model's for the rest.
- `date` is the document's own date, as YYYYMMDD. If the document has no
  date of its own (or the model can't tell what it is), `date` is `null`
  rather than a guess. Today's date and the file's modified time are never
  used.
- Every other field is normalized to hyphen-separated-lower (see
  [Given data](#given-data)).
- `doctype` is one of the configured [doctypes](#classification-settings),
  or `other`.
- `summary` is a single line.
- The model is told the cabinet's `description` and each field's `guidance`
  (see [Fields](#fields)). For fields with
  [learned values](#learned-values), it is also given the common values
  (the same ones offered by tab completion) and asked to reuse one when it
  fits. It is also given the doctype names and descriptions.

For each document it classifies, `classify` prints the document's path in
the intake on stdout. The status on stderr counts the files, e.g.
`Ingested 3 files | Transcribed 3 files | Classified 3 files`.

Other rules:

- A document that already has `results.classify` isn't classified again
  (counted as `Already classified 1 file`; if every document has it, the
  status is `Nothing to classify (1 file already classified)`). There is no
  option to classify it again.
- `--only` classifies only documents that are already ingested and
  transcribed; nothing is ingested or transcribed. Any other file is left
  as it is, with a note on stderr (`Skipped FILE: not ingested yet` or
  `Skipped FILE: not transcribed yet`), and counted in the status, e.g.
  `Skipped 1 file (not transcribed)`.
- If a document fails (transcription or classification fails, the model's
  answer is missing a field, has a field value with no letters or digits,
  or has an unknown doctype, the saved cabinet isn't configured, a
  `--cabinet` differs from the cabinet saved for it, given data conflicts
  with it or names a field its cabinet doesn't have (see
  [Given data](#given-data)), or the sidecar can't be read), the
  error is reported on stderr and the run carries on with the next file.
  The document gets no `results.classify`, so a later run tries it again.
  At the end, the documents that were classified are printed and
  `classify` exits non-zero. This also applies to a single file. A date
  that isn't a valid YYYYMMDD date becomes `null` instead of an error.
- Empty input at the `Cabinet:` prompt skips the document: nothing is
  saved, it is counted as `Skipped`, and a later run asks again.
- The whole configuration (cabinets and doctypes) and the given data are
  checked before any file is touched.

Nothing is stowed: the document stays in the intake.

### Reviewing Files

To confirm, update or redo the proposed records of classified documents:

```bash
filez4eva review
```

`review` works on documents in the [intake](#intake), selected as in
[Which documents, in what order](#which-documents-in-what-order): the new
files given as the path, the documents already in the intake (no path), or
the ones named with `--ingested`. Every document that needs it is
[transcribed](#transcribing-files) first, in one batch (new files are
[ingested](#ingesting-files) before that). Then the documents come one at a
time: each is [classified](#classifying-files) if it hasn't been, then
reviewed, before the next one; its cabinet is chosen before it is
classified, as for `classify` (`--cabinet NAME` or `-c NAME` is accepted
here too, as are `--date`, `--field` and a record on stdin; see
[Given data](#given-data)). With no path, the documents already classified come first. So
the usual flow is `filez4eva classify -c NAME ~/Scans` (unattended), then
`filez4eva review`; to review just one document, give
`filez4eva review --ingested NAME`.

For each document, `review` shows its name (and original name), then the
proposed record from `results.classify`: the summary, doctype, the
document's saved cabinet and the value of each of that cabinet's fields
(`(none)` for a field without a value, e.g. a document without a date).
Values [given](#given-data) for the document are marked, e.g.
`Date: 20240213 (given)`. Then it asks:

```
(c)onfirm (u)pdate (r)edo (x)skip (p)review (d)elete (q)uit
```

- Confirm (c): the classification is right; save it as it is. The proposed
  record (the cabinet and every field value, given ones included) is saved as `results.review`,
  without any prompts, and the document's path is printed on stdout. If a
  field has no value (e.g. no date was found), confirm refuses with a
  message naming the missing fields, e.g. `Missing: date. Use (u)pdate.`,
  and asks again; a value that can't be used (e.g. a date that isn't
  YYYYMMDD in a hand-edited sidecar) is refused the same way, e.g.
  `Invalid: date. Use (u)pdate.`
- Update (u): edit the field values. There is a prompt for each of the
  cabinet's fields, in pattern order, pre-filled with the proposed value
  (empty if there is none); given values are pre-filled the same way and
  can be changed. Press Enter to accept a value, or type a new
  one; tab completion offers the [learned values](#learned-values) of the
  field. An invalid value is rejected and the prompt asks again. Empty
  input goes back to the menu without saving anything. There is no
  `Cabinet:` prompt; to change the cabinet, use redo. Once every field has
  a value, the record is saved as `results.review` and the document's path
  is printed on stdout.
- Redo (r): change the cabinet and classify the document again. With
  several cabinets, it prompts `Cabinet:`, pre-filled with the current
  cabinet, with tab completion of the names (an unknown name is rejected
  and the prompt asks again; empty input goes back to the menu with nothing
  changed). With one cabinet, there is no prompt. The chosen cabinet is
  saved as the document's cabinet (`results.given`, keeping the given
  values of the fields the new cabinet has), the old `results.classify` is
  dropped, and the document is classified again straight away for that
  cabinet's other fields. The new proposal is shown and
  the menu asked again, so you can redo as often as you like. Redo is
  useful with one cabinet too, e.g. after a value was learned from an
  earlier file. If classifying fails, the document fails (see below) and is
  left with the new cabinet and no `results.classify`; the next run
  classifies it again.
- Skip (x): the document is left in the intake as it is, and a later run
  offers it again.
- Preview (p): opens the document with the `preview` command, then asks
  again.
- Delete (d): asks `Delete? [No] (Y)es` and, on `Y`, removes the document,
  its transcript `X.md` and its sidecar `X.yml`.
- Quit (q): ends the run. This document and the rest are left as they are.

Only redo changes the cabinet or `results.classify`. A document classified
before the cabinet was saved separately (its sidecar has
`results.classify.cabinet` and no `results.given`) is reviewed for that
cabinet.

When a record is saved as `results.review` (confirm, update, or complete
given data), the values of the cabinet's fields with
[learned values](#learned-values) are recorded straight away, so tab
completion and classification of the next documents in the same run can
use them once they've been used twice. If they can't be recorded, a
warning is shown and the review is kept.

The status on stderr counts the files, e.g.
`Reviewed 2 files | Skipped 1 file | Deleted 1 file`, with `Quit` at the end
if you quit.

Other rules:

- A document that already has `results.review` isn't offered again
  (counted as `Already reviewed 1 file`; if every document has it, the
  status is `Nothing to review (1 file already reviewed)`).
- With [complete given data](#given-data) (the cabinet and every field),
  a document isn't classified or shown: the record is saved as
  `results.review` with `input: true`, and counted as `Given`.
- `--only` reviews only documents that are already ingested, transcribed
  and classified; nothing is ingested, transcribed or classified. Any other
  file is left as it is, with a note on stderr
  (e.g. `Skipped FILE: not classified yet`), and counted in the status, e.g.
  `Skipped 1 file (not classified)`.
- If a document fails (an earlier stage fails, its `results.classify` can't
  be used, its saved cabinet isn't configured when you confirm or update
  (redo can choose a configured one), a `--cabinet` differs from the
  cabinet saved for it, given data conflicts with it, classifying it again
  at redo fails, or its
  sidecar can't be read), the error is
  reported on stderr
  and the run carries on with the next file. At the end, the documents that
  were reviewed are printed and `review` exits non-zero.
- The whole configuration (cabinets and doctypes) and the given data are
  checked before any file is touched.

Nothing is stowed: the document stays in the intake. To review and stow in
one pass, use [`stow`](#stowing-files).

### Stowing Files

To review and stow every document in the intake:

```bash
filez4eva stow
```

`stow` selects documents as in
[Which documents, in what order](#which-documents-in-what-order): the new
files given as the path, the documents already in the [intake](#intake) (no
path), or the ones named with `--ingested`. New files are
[ingested](#ingesting-files), and every document that needs it is
[transcribed](#transcribing-files), all up front. Then the documents come
one at a time: each is [classified](#classifying-files) and
[reviewed](#reviewing-files) if it hasn't been, then stowed, before the next
one starts. With no path, the most advanced come first: `filez4eva stow`
stows the documents already reviewed (without asking), then reviews and
stows the classified ones, then classifies, reviews and stows the rest. So
the main use case is:

```bash
filez4eva classify -c NAME ~/Scans   # unattended: ingest, transcribe, classify
filez4eva stow                       # interactive: confirm or update, then stow
```

As for `classify`, a document's cabinet is chosen before it is classified:
`--cabinet NAME` (or `-c NAME`) gives it for every document in the run that
has none saved yet; without it, and with several cabinets, `stow` prompts
`Cabinet:` for each such document. A `--cabinet` that differs from the
cabinet already saved for a document fails that document (e.g.
`filez4eva classify -c accounts ~/Scans`, then
`filez4eva stow -c memories`); the run carries on with the others.
`--date`, `--field` and a record on stdin give values for every document
too; with the cabinet and every field given, each document is stowed
without the model or any prompt (see [Given data](#given-data)).

To review and stow every file in a directory in one interactive pass, give
the directory: `filez4eva stow ~/Scans`. That leaves the documents already
in the intake alone. To stow some of those, name them:
`filez4eva stow --ingested 20261025-140307-042.pdf`.

For each document that hasn't been reviewed, `stow` shows the proposed
record and offers the same menu as [`review`](#reviewing-files): confirm,
update, redo, skip, preview, delete or quit. A confirmed or updated
document is stowed
straight away, before the next one is shown. A document that was already
reviewed is stowed without asking. A skipped document stays in the intake
with its results, and the next `stow` offers it again.

Stowing a document:

1. moves the file into the cabinet's target, named by the cabinet's
   [pattern](#destination-pattern) with the file's extension kept, and its
   transcript `X.md` with it, named after the stowed file: by default next
   to it (`.../20261002-receipt.pdf` gets `.../20261002-receipt.pdf.md`),
   or in a parallel tree (see [Transcript location](#transcript-location)).
   Missing directories are created. If the transcript can't be moved, the
   file is moved back. Stowing records no
   [learned values](#learned-values): they were recorded when the record
   was reviewed.
2. records `results.stow` in its sidecar `X.yml`: when it was stowed and
   where the file went (see [The X.yml sidecar](#the-xyml-sidecar)).
3. moves `X.yml` to `<intake>/archive/`, for later reference.

The absolute destination path is printed on stdout, so a script can
capture it, e.g.
`dest=$(filez4eva stow -d 20240213 -f title=receipt file.pdf)` (with
[complete given data](#given-data), nothing else is printed on stdout and
nothing is asked).

- The cabinet and field values come from `results.review`.
- An existing file is never overwritten. If something already exists where
  the file, its transcript or its archived `X.yml` would go, the document
  fails before anything moves and stays in the intake.
- `--only` stows only documents already ingested, transcribed, classified
  and reviewed. Any other file is left as it is, with a note on stderr
  (e.g. `Skipped FILE: not reviewed yet`), and counted in the status, e.g.
  `Skipped 1 file (not reviewed)`. Nothing is ingested, transcribed,
  classified or reviewed. So `filez4eva review --ingested NAME` followed by
  `filez4eva stow --only` stows just the reviewed documents, without any
  prompts and without dealing with the others.
- If a document fails, the error is reported on stderr and the run carries
  on with the next file. At the end, the documents that were stowed are
  printed and `stow` exits non-zero. If the file was stowed but its sidecar
  couldn't be archived, the error says where the file went.
- The whole configuration (cabinets and doctypes) and the given data are
  checked before any file is touched.

The status on stderr counts the files, e.g.
`Reviewed 2 files | Stowed 3 files | Skipped 1 file`, with `Quit` at the end
if you quit.

### Given data

When you already know some of the values for a batch of documents (their
cabinet, their date, a field), give them on the command line or on stdin.
`classify`, `review` and `stow` all take given data, and it applies to every
document the run works on: a file, a directory, the documents in the intake
(no path), or the ones named with `--ingested`. Classification then fills in
only the rest.

- `--cabinet NAME` (or `-c NAME`): the cabinet.
- `--date DATE` (or `-d DATE`): the date, as YYYYMMDD, e.g. `20240213`.
- `--field NAME=VALUE` (or `-f NAME=VALUE`, repeatable): the value of any
  other field.
- A YAML record on stdin, with the cabinet under `cabinet` and the fields
  (`date` included) under `data`.

For example, for a cabinet `accounts` whose pattern is
`{date.year}/{account}/{date}_{part}`:

```bash
# Every scan in ~/Scans is from the bank, dated 13 Feb 2024: the model
# proposes only the part, and review shows the rest marked (given)
filez4eva classify -c accounts -d 20240213 -f account=royal-bank ~/Scans
filez4eva stow

# Everything given: no model call, no review menu, no prompts
dest=$(filez4eva stow -c accounts -d 20240213 -f account=royal-bank \
  -f part=visa ~/Desktop/statement.pdf)

printf 'cabinet: accounts\ndata:\n  date: 2024-02-13\n  account: royal-bank\n  part: visa\n' \
  | filez4eva stow ~/Desktop/statement.pdf
```

How given data is used, for each document in the run:

1. **Saved with the document.** Before the document is classified, its
   cabinet is chosen as usual (the cabinet already saved for it, then the
   given cabinet, then the only cabinet, then a `Cabinet:` prompt; see
   [How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen)),
   and the given values of that cabinet's fields are saved with it as
   `results.given.data` in its [sidecar](#the-xyml-sidecar), so later
   commands use them. Values given by an earlier run are kept, and new ones
   are added.
2. **Classification fills in only the rest.** The model is asked only for
   the cabinet's fields that weren't given (plus the doctype and summary);
   it is told the given values. The proposed record in `results.classify` is
   the given values plus the classified ones.
3. **Review shows them, marked.** At [review](#reviewing-files), the given
   values are shown with the rest, marked as given, e.g.
   `Date: 20240213 (given)`. Confirm accepts them. Update pre-fills them
   like any other value and can change them (the record saved is what you
   enter; `results.given` keeps what was given). Redo keeps the given values
   of the fields the new cabinet has.
4. **Complete given data skips the model and the menu.** With the cabinet
   and every one of its fields given (by this run, or saved by an earlier
   one), there is no model call and no review menu: the record is saved as
   `results.review`, with `input: true`, its
   [learned values](#learned-values) are recorded (once per document), and
   it is counted as `Given` in the status (e.g. `Ingested 3 files | Transcribed 3 files | Given 3 files |
   Stowed 3 files`). `stow` then stows the document without prompts and
   prints only its destination, so
   `dest=$(filez4eva stow -d 20240213 -f title=receipt file.pdf)` works in
   a script. `classify` and `review` record it the same way, print the
   document's path and don't prompt. A later `stow` (even `stow --only`)
   stows it. Under `--only`, complete given data stands in for classify and
   review when the cabinet is known without asking. The same goes for a
   document already classified but not reviewed, when every value given
   equals its classified one (see Conflicts below): `review` and `stow`
   record it as `results.review` with `input: true` and show no menu.

Nothing is prompted for before the run: a missing value is what
classification fills in, and review covers the rest. The cabinet is still
prompted for, per document, if it isn't given and there are several.

Checks:

- **Before anything moves:** an unknown cabinet (from `--cabinet` or
  stdin), an invalid date, a malformed `--field`, or a value with nothing
  left once normalized (see below) is an error before any file is touched.
  When the run's cabinet is known up front (given, or the only one), a
  `--field` name that isn't one of its fields is an error too. Use
  `--date`, not `--field date=...`, for the date.
- **Per document:** with several cabinets and no `-c`, the cabinet is chosen
  per document, so a `--field` name that the chosen cabinet doesn't have
  fails that document only (`Unknown field account for cabinet memories;
  known: event`); the run carries on with the others. Nothing is saved for
  that document, not even a cabinet chosen at the `Cabinet:` prompt, so the
  next run asks for it again (and a wrong choice can be corrected).
- **Conflicts fail that document only:** a given value that differs from
  the value already given for the document (e.g.
  `Date 20240213 given, but 20261025-140307-042.pdf already has date 20240101`),
  a given cabinet that differs from its saved cabinet, or a given value for
  a document that is already classified or reviewed (e.g.
  `Part visa given, but 20261025-140307-042.pdf is already classified with part receipt`)
  is reported and the run carries on. Equal values are fine: giving a
  reviewed document the values it already has stows it as reviewed.

The flags and stdin:

- Flags win over stdin.
- `--date` must be YYYYMMDD, e.g. `20240213`. On stdin, `date` may be
  `20240213`, `'20240213'` or `2024-02-13`.
- On stdin, the recognised keys are `cabinet` and `data`; any other
  top-level keys are ignored. Under `data`, keys that aren't fields of the
  document's cabinet are ignored (unlike `--field` names).
- Stdin that is empty, isn't valid YAML, isn't a mapping, or has neither a
  `cabinet` nor `data` is ignored (so the command runs as usual). A `data`
  value that isn't a mapping, or a value that isn't a single value, is an
  error.
- Values on stdin are read as plain text, so `0123` stays `0123` and `yes`
  stays `yes`. `~` and `null` are treated as missing, so that value is left
  to classification.
- A given value applies to every document in the run; there is no way to
  give a different record for each file of a directory.

However the values are supplied (flags, stdin, prompts or the AI), every
field other than `date` ends up hyphen-separated-lower: accents are
stripped, letters are lowercased, and each run of anything other than `a-z`
and `0-9` becomes a single hyphen, trimmed at both ends. So
`Royal Bank of Canada` becomes `royal-bank-of-canada`, and the value can
never contain `/` or `..`. A value with nothing left (such as `../`) is
rejected: from a flag or stdin, the command exits with an error before
anything moves; typed at a prompt, the prompt asks again. A normalized value
typed at a prompt is used without asking again.

### Command Line Options

`filez4eva --help` lists the commands, and `filez4eva COMMAND --help`
describes a command and its options.

Global options:
- `--config PATH`: Specify path to config file
- `--debug`: Enable debug output

ingest command:
- `--meta, -m KEY=VALUE`: Record source metadata (repeatable)
- `path`: Path to the file, or directory of files, to ingest

The stage commands (`transcribe`, `classify`, `review` and `stow`) all take
(see [Which documents, in what order](#which-documents-in-what-order)):
- `path`: Optional new files: a file, or a directory (top level only),
  outside the intake. Without it, the documents already in the intake.
- `--ingested NAME`: Work on this document already in the intake (its file
  name there, or a path to it) and no other; repeatable, taken in the order
  given; not with a path

`classify`, `review` and `stow` also take [given data](#given-data) for
every document in the run (and a YAML record on stdin):
- `--cabinet, -c NAME`: The cabinet of every document in the run that has
  none saved yet, instead of a `Cabinet:` prompt for each one (see
  [How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen))
- `--date, -d DATE`: The date of every document in the run, as YYYYMMDD
- `--field, -f NAME=VALUE`: The value of a field for every document in the
  run (repeatable)

transcribe command:
- `--only`: Transcribe only documents already ingested; skip other files

classify command:
- `--only`: Classify only documents already ingested and transcribed; skip
  other files

review command:
- `--only`: Review only documents already ingested, transcribed and
  classified; skip other files

stow command:
- `--only`: Stow only documents already ingested, transcribed, classified
  and reviewed; skip other files (with complete given data: ingested and
  transcribed)

## Configuration

Create a `filez4eva.yml` file with:

```yaml
filez4eva:
  intake: '~/Dropbox/intake'   # Optional; default ~/.filez4eva/intake
  target: '~/Dropbox/accounts' # Target directory for stowed files
```

By default, files are stowed directly under the target, named after their
date and a title, keeping their extension:
```
~/Dropbox/accounts/<date>-<title>.<extension>
```

### Intake

The intake is the directory where documents wait between stages. `ingest`
(or any other command, given a file outside the intake) moves files into
it. Given no path, the stage commands work on the documents already in it
(or, with `--ingested NAME`, on the ones named). It is set with the
optional `intake` key:

```yaml
filez4eva:
  intake: '~/Dropbox/intake'   # Default: ~/.filez4eva/intake
```

It defaults to `~/.filez4eva/intake`, and is created (with any missing
parent directories) if it doesn't exist. It can also be set with the
`FILEZ4EVA_INTAKE` environment variable.

When [`stow`](#stowing-files) stows a document, its sidecar `X.yml` moves to
`<intake>/archive/`. The stage commands only look at the top level of the
intake, so archived sidecars are never documents. Nothing removes them.

### The X.yml sidecar

Each document in the intake, `X`, has a sidecar file `X.yml` next to it (the
full name plus `.yml`, so `20261025-140307-042.pdf` has
`20261025-140307-042.pdf.yml`). Each stage that works on the document
records its results under `results`, keyed by the stage. `ingest` writes:

```yaml
results:
  ingest:
    at: '2026-10-25T14:03:07-07:00'
    original-name: Report.DOCX.pdf
    source:
      from: email
      via: scanner
```

- `at`: when the file was ingested, in ISO-8601 local time with its UTC
  offset, to the second. It is the same moment as the file's new name
  (unless the stamp had to move on a millisecond or more).
- `original-name`: the file's name before it was ingested.
- `source`: the metadata from `--meta` and stdin, as text. It is `{}` when
  there is none.

`transcribe` adds:

```yaml
results:
  ingest: ...
  transcribe:
    at: '2026-10-25T14:03:12-07:00'
    model: claude-opus-4-6
    transcript: 20261025-140307-042.pdf.md
    length: 5321
```

- `at`: when the transcript was written or found up to date, in ISO-8601
  local time with its UTC offset, to the second.
- `model`: the model that made the transcript (from its front matter).
- `transcript`: the transcript's file name, next to the document. It is
  always `X.md`; `classify` fails a document whose sidecar names any other
  file, and `review`'s delete removes `X.md` whatever the sidecar says.
- `length`: the length of the transcribed Markdown in characters, without
  the front matter and disclaimer.

Before a document is classified (by `classify`, or by `review` or `stow`
running classify first), its cabinet is chosen (see
[How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen))
and saved as `results.given`, with any [given](#given-data) field values,
before the model is asked:

```yaml
results:
  ingest: ...
  transcribe: ...
  given:
    at: '2026-10-25T14:03:14-07:00'
    cabinet: accounts
    data:
      date: '20240213'
```

- `at`: when the cabinet and values were given, in ISO-8601 local time with
  its UTC offset, to the second.
- `cabinet`: the document's cabinet. Later commands use it without asking,
  and a `--cabinet` that differs from it fails the document. If the
  document is skipped at the `Cabinet:` prompt, nothing is saved.
- `data` (only when values are given): the given values of the cabinet's
  fields, in pattern order, with `date` as YYYYMMDD. The model isn't asked
  for them, and a later run that gives a different value fails the
  document.

`results.given` holds what is given for a document rather than proposed by
the model.

`classify` then adds:

```yaml
results:
  ingest: ...
  transcribe: ...
  given: ...
  classify:
    at: '2026-10-25T14:03:15-07:00'
    model: claude-haiku-4-5
    doctype: receipt
    summary: Amazon.ca order receipt for a USB hub
    data:
      date: '20261002'
      title: usb-hub-receipt
```

- `at`: when the document was classified, in ISO-8601 local time with its
  UTC offset, to the second.
- `model`: the model that classified it.
- `doctype`, `summary` and `data`: the classification (see
  [Classifying Files](#classifying-files)). `data` has a value for each of
  the fields of the cabinet in `results.given`, in pattern order, with
  `date` as YYYYMMDD or `null`.

Sidecars written before `results.given` was introduced have none, and hold
the cabinet in `results.classify.cabinet` instead. They keep working: that cabinet (or, for a reviewed document,
`results.review.cabinet`) is taken as the saved cabinet. They aren't
rewritten.

`review` adds, when you confirm or update the record:

```yaml
results:
  ingest: ...
  transcribe: ...
  given: ...
  classify: ...
  review:
    at: '2026-10-25T15:20:41-07:00'
    cabinet: accounts
    data:
      date: '20261002'
      title: usb-hub-receipt
```

- `at`: when the record was confirmed or updated, in ISO-8601 local time with its UTC
  offset, to the second.
- `cabinet`: the document's cabinet, from `results.given` (only redo at
  review changes it).
- `data`: the confirmed value of each of that cabinet's fields, in pattern
  order, with `date` as YYYYMMDD.

With [complete given data](#given-data) (the cabinet and every field),
`classify`, `review` or `stow` writes `results.review` itself, in the same
shape, with `input: true`, together with `results.given`, and there is no
`results.classify`:

```yaml
results:
  ingest: ...
  transcribe: ...
  given: ...
  review:
    at: '2026-10-25T15:20:41-07:00'
    input: true
    cabinet: accounts
    data:
      date: '20261002'
      title: usb-hub-receipt
```

`stow` adds, once the file is in the cabinet, and then moves the sidecar to
`<intake>/archive/`:

```yaml
results:
  ingest: ...
  transcribe: ...
  given: ...
  classify: ...
  review: ...
  stow:
    at: '2026-10-25T15:20:42-07:00'
    location: /Users/me/Dropbox/accounts/20261002-usb-hub-receipt.pdf
```

- `at`: when the document was stowed, in ISO-8601 local time with its UTC
  offset, to the second.
- `location`: the absolute path of the stowed file.

`stow` stows with the cabinet and data in `results.review`. A hand-edited
sidecar is checked first: an unknown cabinet or an invalid value fails the
document without moving anything.

Keys use hyphens. A file in the intake counts as ingested only if its
sidecar exists; the sidecar is written before the file is moved in, so a
failure never leaves a file in the intake without one.

### Destination pattern

The layout under `target` can be changed with the optional `pattern` key:

```yaml
filez4eva:
  target: '~/Dropbox/accounts'
  pattern: '{date.year}/{account}/{date}_{part}'
```

The default is `'{date}-{title}'`. Quote the pattern in YAML, since it
starts with `{`.

The pattern is the only place the cabinet's fields are named: each
placeholder is a field, and the fields are prompted for (and shown to the
AI) in the order they first appear. A field's first placeholder sets its
position, whether or not it has a modifier, so with
`'{date.year}/{account}/{date}_{part}'` the order is date, account, part.
Placeholders:
- `{date}`: the date as YYYYMMDD, e.g. `20240213`. Every pattern must
  contain `{date}`.
- `{date.year}`: the date's four-digit year, e.g. `2024`. It doesn't count
  as `{date}`, but it does set the date's position in the field order.
- `{name}`: any other field, where `name` is lowercase letters, digits and
  underscores, starting with a letter (e.g. `{title}`, `{account}`,
  `{event}`). Its value is hyphen-separated-lower.

The source file's extension (e.g. `.pdf`) is always added to the end, so
don't put it in the pattern. Use `/` to create subdirectories; missing
directories are created. `{{` and `}}` are literal braces, and any other
text is used literally. Since field values contain hyphens, use another
separator such as `_` between two fields if you want to tell them apart
later.

A pattern is a configuration error, and `classify`, `review` and `stow` exit
before touching any file or prompting, if it:
- doesn't contain `{date}`
- has a placeholder that isn't a valid field name, such as `{}`, `{0}`,
  `{Title}`, `{title:>4}`, `{title!r}` or `{title[0]}`
- has a modifier other than `{date.year}`
- has unbalanced braces
- is absolute, starts with `~`, or contains `..`

### Fields

Each field can have settings under `fields`, keyed by the field name:

```yaml
filez4eva:
  target: '~/Dropbox/accounts'
  pattern: '{date.year}/{account}/{date}_{part}'
  fields:
    date:
      guidance: The transaction or statement date, not the print date
    account:
      guidance: The organization on the other side of the transaction, never me
    part:
      guidance: The kind of document, such as visa-statement or tax-receipt
      values: learned
```

- `guidance` is shown to the AI model when it proposes a value for the
  field. For `date`, it replaces the built-in description, but the fixed
  rules always apply: the value is YYYYMMDD, the model must not guess, and
  it is empty if the document has no date of its own.
- `values` says whether filez4eva keeps a list of the field's values:
  `learned` (see [Learned values](#learned-values)) or `none`. `date` can't
  have `values`. A fixed list of values is not yet supported.

Without settings, `date` and `title` have simple built-in guidance, and other
fields have none. `title` defaults to `values: none`, and every other field
except `date` defaults to `values: learned`.

Each setting is looked up in the cabinet's own `fields`, then the top-level
`fields`, then the built-in default. A field set in a cabinet's `fields` but
not in its pattern is a configuration error, as is a top-level field that no
pattern uses, so typos are caught. Other configuration errors are a field
name that isn't valid, a setting other than `guidance` or `values`, guidance
that isn't text, and an unknown `values`.

### Learned values

For fields with `values: learned`, filez4eva remembers the values it files,
in `.filez4eva/values.yaml` inside each cabinet's target:

```yaml
account:
  amazon:
    count: 3
    last_used: '2026-10-15'
```

- The values are recorded when a document's record is accepted, that is
  when `results.review` is saved: at [review](#reviewing-files) (in
  `review`, or in `stow` for a document not reviewed yet) on confirm or
  update, or from [complete given data](#given-data) (`input: true`).
  Wherever a value came from (the model, flags, stdin or a prompt), each
  document counts once. `classify` without complete given data records
  nothing, and `stow` records nothing: a document's values stay counted
  even if stowing it later fails or it is deleted after review. Existing
  files aren't scanned, so the list starts empty.
- Tab completion, and the AI model, are offered values used at least twice,
  most-used first, at most 100 per field. A value used once is remembered,
  but only offered once it is used again.
- The file is read afresh for every document, so a value that reaches two
  uses during a run (e.g. typed at update for two documents) is offered for
  the next document in the same run, to the model and at the prompts.
- You can seed or prune the list by editing the file. Values that aren't
  hyphen-separated-lower are never offered.
- The file is written to a temporary file and renamed, so a synced target
  never sees a half-written file. If it can't be read or written, the
  review is still saved, a warning is shown, and the existing file is left
  as it was.

### Cabinets

To file into more than one destination, configure named cabinets:

```yaml
filez4eva:
  fields:
    date:
      guidance: The date the document was issued
  cabinets:
    finances:
      target: ~/Dropbox/finances
      pattern: '{date.year}/{account}/{date}_{part}'
      description: Personal financial records
      fields:
        account:
          guidance: The organization on the other side of the transaction, never me
    memories:
      target: ~/Dropbox/memories
      pattern: '{event}/{date}'
      fields:
        date:
          guidance: When the photo was taken
        event:
          guidance: The occasion, such as grandma-80th-birthday
    linkedin:
      target: ~/Dropbox/linkedin
```

Each cabinet has:
- `target` (required): the directory files are stowed under
- `pattern` (optional): the layout under the target, as described above,
  which also sets the cabinet's fields. Defaults to the top-level `pattern`
  if set, otherwise `'{date}-{title}'`. The set of fields always comes from
  one pattern as a whole; patterns are never combined.
- `fields` (optional): settings for the fields in the cabinet's pattern,
  which win over the top-level `fields`; see [Fields](#fields)
- `description` (optional): a note on what the cabinet holds, shown to the
  AI model
- `transcripts` (optional): where transcripts of files stowed in this cabinet
  go, with `location` and `root` keys. Each key defaults to the top-level
  `transcripts` value; see [Transcript location](#transcript-location)

#### How a document's cabinet is chosen

You choose each document's cabinet; the AI model never picks it. It is
chosen before the document is classified, so the model fills in that
cabinet's fields, guided by its description, field guidance and learned
values. This happens one document at a time, in the per-document part of
`classify`, `review` and `stow` (whichever runs classify for it). The
first of these that applies wins:

1. **The cabinet already saved for the document** (`results.given.cabinet`
   in its [sidecar](#the-xyml-sidecar); for a sidecar from before
   `results.given`, the cabinet in `results.review` or `results.classify`).
2. **`--cabinet NAME` (or `-c NAME`)** on `classify`, `review` or `stow`,
   for every document in the run (or `cabinet` in a record on stdin).
3. **The only cabinet**, when just one is configured: no prompt.
4. **A `Cabinet:` prompt** for that document, after a line naming it (and
   its original name), with tab completion of the cabinet names. An unknown
   name is rejected and the prompt asks again. Empty input skips the
   document: nothing is saved, it is counted as `Skipped`, and a later run
   asks again.

The cabinet is saved as `results.given` before the model is asked, so later
commands use it without asking: `review` and `stow` don't prompt for the
cabinet of a classified document (unless you choose redo at review). So with several cabinets and no `-c`,
`classify` prompts for each document; to run it unattended, give
`filez4eva classify -c NAME ~/Scans`.

- An unknown `--cabinet` name is an error before any file is touched.
- A `--cabinet` that differs from the cabinet already saved for a document
  fails that document, with an error such as
  `Cabinet memories given, but 20261025-140307-042.pdf already has cabinet accounts`;
  the run carries on with the others. For example,
  `filez4eva classify -c accounts ~/Scans` followed by
  `filez4eva stow -c memories` fails every document from `~/Scans`. The
  same cabinet is fine.
- A `cabinet` key in a record on stdin (see [Given data](#given-data))
  counts as `--cabinet NAME` when there is no `--cabinet`. An unknown name
  from stdin is an error before any file is touched.
- At review, redo (r) changes the cabinet: it saves the chosen one as
  `results.given` and classifies the document again (see
  [Reviewing Files](#reviewing-files)).

Prompts, tab completion and learned values use the chosen cabinet's fields
and target.

If there is no `cabinets` section (or it is empty), the top-level `target`,
`pattern` and `fields` form a single cabinet named `default`. If `cabinets`
is present, the top-level `target` is ignored.

The whole configuration is checked before any prompt: a cabinet with no
`target`, or with an invalid pattern, fields or transcripts setting, is an
error even if it isn't the one being used.

### Transcript location

When `stow` stows a document, its transcript goes next to the stowed file
by default (`adjacent`). To keep transcripts in a
parallel tree instead:

```yaml
filez4eva:
  transcripts:
    location: parallel           # or 'adjacent' (the default)
    root: ~/Dropbox/transcripts
```

With `location: parallel`, the transcript goes to
`<root>/<cabinet>/<path under the cabinet target>.md`. For example, stowing
into the `finances` cabinet at `2026/amazon/20261002_receipt.pdf` puts the
transcript at `~/Dropbox/transcripts/finances/2026/amazon/20261002_receipt.pdf.md`.
Missing directories are created, and the root may be on another filesystem.
Without a `cabinets` section the single cabinet is named `default`, so
transcripts go under `<root>/default/`.

A cabinet can override either key with its own `transcripts` block; a key it
doesn't set falls back to the top-level value:

```yaml
filez4eva:
  transcripts:
    location: parallel
    root: ~/Dropbox/transcripts
  cabinets:
    accounts:
      target: ~/Dropbox/accounts         # transcripts in the parallel tree
    memories:
      target: ~/Dropbox/memories
      transcripts:
        location: adjacent               # transcripts next to the files
```

A `location` other than `adjacent` or `parallel`, `parallel` without a
`root`, or a `transcripts` value (top-level or in a cabinet) that isn't a
mapping is a configuration error, and `classify`, `review` and `stow` exit
before prompting or touching any file. An error in a top-level setting names the top level rather
than a cabinet. An empty `transcripts:` block, or an empty `location`, counts
as unset, but other values such as `no` or `0` are rejected as invalid
locations.

This only affects `stow`. Until a document is stowed, `transcribe` keeps
its transcript next to it in the intake (also when `classify` or another
command transcribes it).

### Transcription settings

`transcribe` uses these optional keys:

```yaml
filez4eva:
  transcribe:
    model: claude-opus-4-6              # Anthropic model ID
  anthropic:
    key: op://vault/anthropic/credential
```

- `transcribe: model:` defaults to `claude-opus-4-6`.
- `anthropic: key:` is the Anthropic API key. Like other config values, it
  may be a 1Password secret reference (`op://vault/item/field`, as copied
  with 1Password's "Copy Secret Reference"), which is read using the `op`
  CLI. This needs `op` installed and signed in. If `op` is missing or fails,
  Filez4Eva reports a config error and stops.
- `$(...)` command substitution in config values is no longer supported;
  such a value is now used as literal text. To migrate, replace
  `$(op read op://...)` with just `op://...`.
- The key can also be set with the `FILEZ4EVA_ANTHROPIC_KEY` environment
  variable, which takes precedence over the config file. Its value is used
  as given; an `op://` reference there is not read. If neither is set, the
  Anthropic SDK's own `ANTHROPIC_API_KEY` environment variable is used.

Filez4Eva only reads its own configuration; Kwark's configuration is never
used.

### Classification settings

`classify` uses these optional keys, as well as the `transcribe` model and
the `anthropic` key above:

```yaml
filez4eva:
  classify:
    model: claude-haiku-4-5     # Anthropic model ID (the default)
  doctypes:
    receipt:
      description: Proof of purchase or payment
    bill:
      description: A request for payment, usually with a due date
```

- `classify: model:` defaults to `claude-haiku-4-5`. Transcription still
  uses `transcribe: model:`.
- `doctypes` maps each document type to an optional `description`, which is
  shown to the model. Names must be single words (letters, digits, `-` and
  `_`). `other` is always available; configure it only to change its
  description. With no `doctypes`, every document's doctype is `other`.
- A `doctypes` value that isn't a mapping, a name that isn't a single word,
  or a description that isn't text is a configuration error, and `classify`
  exits before calling the model.

### Migrating from stow-file, scan-dir and process

The `stow-file`, `scan-dir` and `process` commands have been removed, with
no aliases: running one gives the usual error for an unknown command.
Running `filez4eva` with no command no longer scans a directory; it is an
error too. Use the [five commands](#the-five-commands) instead:

| Instead of | Use |
|------------|-----|
| `filez4eva stow-file FILE` with `--date`, `--field NAME=VALUE` or a record on stdin (and possibly `--cabinet`) giving every value | `filez4eva stow FILE` with the same flags or stdin record: no model call and no prompts, and only the destination is printed. The same works for a directory or the intake. See [Given data](#given-data). |
| `filez4eva stow-file FILE` with some values given, typing the rest at the prompts | `filez4eva stow FILE` with the values you know (e.g. `filez4eva stow -c CABINET -d DATE FILE`): the model proposes the rest, and you confirm or update the record. Nothing is prompted for before the run. |
| `filez4eva stow-file FILE`, typing every value at the prompts | `filez4eva stow -c CABINET FILE` to have the model propose the values for that cabinet, which you confirm or update (update edits every value). |
| `filez4eva scan-dir DIR`, or `filez4eva` on its own with `source:` configured | `filez4eva classify -c NAME DIR` (unattended), then `filez4eva stow`; or `filez4eva stow DIR` for one interactive pass. The menu offers confirm, update, redo, skip, preview, delete and quit. |
| `filez4eva process FILE` | `filez4eva stow FILE`: it asks for the cabinet if there are several, transcribes and classifies the file, asks you to confirm or update the record, then stows it. |
| `filez4eva process --cabinet NAME FILE` | `filez4eva stow --cabinet NAME FILE`, or `filez4eva classify --cabinet NAME FILE`, then `filez4eva stow`. |
| `filez4eva process --dry-run FILE` | `filez4eva review FILE`, which saves the confirmed record without moving the file into a cabinet; then `filez4eva stow`. |

Differences to be aware of:

- **You choose the cabinet; the model never picks it.** With several
  cabinets and no `-c NAME`, `classify` (and `review` and `stow`, for a
  document they classify) prompts `Cabinet:` for each document before
  classifying it. The unattended main use is now
  `filez4eva classify -c NAME ~/Scans`. See
  [How a document's cabinet is chosen](#how-a-documents-cabinet-is-chosen).
- `review` no longer has a `Cabinet:` prompt when you accept a record:
  the cabinet saved before classify is used. Confirm (c) now saves the
  proposed record as it is, without prompts; update (u) edits the values,
  and redo (r) changes the cabinet and classifies again.
- [Given data](#given-data) (`--cabinet`, `--date`, `--field` and a record
  on stdin) works on `classify`, `review` and `stow`, for every document in
  the run: a file, a directory, the intake or `--ingested`. Only the
  values you don't give are classified, and with every value given there
  is no model call and no review. Missing values are never prompted for:
  the model proposes them and you confirm or update them at review. `-c
  CABINET` on its own gives the cabinet, and the file is classified and
  reviewed as usual.
- A given value that conflicts with what a document already has (a
  different given value, or any different value for a document already
  classified) fails that document; equal values are fine.
- Every file now goes through the [intake](#intake) on its way to a
  cabinet: it is moved there and renamed when it is ingested, and its
  transcript `X.md` is written there, rather than next to the original
  file. Where it ends up in the cabinet is the same as before.
- `stow FILE` transcribes the file before stowing it, even with every value
  given, so it needs an Anthropic API key (see
  [Transcription settings](#transcription-settings)) and a supported file
  type, which `stow-file` didn't.
- A directory is handled at its top level only: unlike `scan-dir`,
  subdirectories are left alone.
- The `source:` configuration key is no longer used and can be removed.
- Status lines on stderr count the files of each stage, e.g.
  `Ingested 1 file | Transcribed 1 file | Stowed 1 file`, instead of
  `stow-file`'s `Done`. The destination path is still printed on stdout.

### Upgrading from version 5

Version 6 replaces the fixed `account` and `part` with fields named by each
cabinet's pattern:
- The default pattern is now `{date}-{title}`, directly under the target. To
  keep the old layout, set `pattern: '{date.year}/{account}/{date}-{part}'`.
  The prompts then come in the same order as before: date, account, part.
- `{year}` is now `{date.year}`, and `{ext}` is no longer used: the
  extension is always added. In a version 6 pattern, `{year}` or `{ext}`
  would be an ordinary field that you are prompted for.
- `stow-file --account/-a` and `--part/-p` are replaced by `--field/-f
  NAME=VALUE` (`stow-file` has since been removed; `stow` takes the same
  flags: see
  [Migrating from stow-file, scan-dir and process](#migrating-from-stow-file-scan-dir-and-process)).
- In a record on stdin, the fields (including `date`) are under `data:`.
- Field values are normalized to hyphen-separated-lower, so existing
  directories with capitals or spaces won't match new values.
- Tab completion no longer scans existing folders; it offers
  [learned values](#learned-values) instead. Existing files are not moved.
