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
| [`classify`](#classifying-files) | Has an AI model propose a cabinet and a value for each of its fields, for each document | No |
| [`review`](#reviewing-files) | Shows each proposed record, to confirm or edit | Yes |
| [`stow`](#stowing-files) | Moves each confirmed document and its transcript into its cabinet, named by the cabinet's pattern | For documents not yet reviewed |

The main use case is two commands:

```bash
filez4eva classify ~/Scans   # unattended: ingest, transcribe and classify every file
filez4eva stow               # interactive: confirm or edit each record, then stow it
```

How the stages fit together:

- **The intake** is the holding area where documents wait between stages: a
  directory, `~/.filez4eva/intake` unless you set the `intake:` key in the
  [configuration](#intake). `ingest` moves files into it and renames them.
- **A path** can be a file, a directory (its top level only) or, except for
  `ingest`, left out for every document in the intake. A file outside the
  intake is ingested first.
- **Earlier stages run as needed.** Each command runs any earlier stage a
  document hasn't had yet, so `filez4eva stow ~/Scans` alone ingests,
  transcribes, classifies, reviews and stows every file in `~/Scans`.
- **The `X.yml` sidecar** next to each document `X` in the intake records
  the result of each stage under `results.<stage>` (see
  [The X.yml sidecar](#the-xyml-sidecar)). A stage that's already recorded
  isn't run again, so you can stop at any point and carry on later. Once a
  document is stowed, its sidecar moves to `<intake>/archive/`.
- **`--only`** makes `transcribe`, `classify`, `review` or `stow` act only on
  documents that have had every earlier stage, and skip the rest with a note
  on stderr, instead of running the missing stages. For example,
  `filez4eva review` followed by `filez4eva stow --only` stows the reviewed
  documents without any prompts.

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

`transcribe` works on documents in the [intake](#intake). A file that isn't
there yet is [ingested](#ingesting-files) first (moved into the intake and
renamed), then transcribed. The transcript `X.md` (the full name plus `.md`)
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
filez4eva transcribe ~/Desktop/scans   # every file in the directory
filez4eva transcribe                   # every document in the intake
```

`transcribe` works out whether the path is a file or a directory. Which
files are documents:

- Outside the intake, every non-hidden regular file at the top level of the
  directory is a new document, and is ingested first. Subdirectories, hidden
  files (names starting with `.`) and symbolic links are left alone.
- In the intake, a document is a file `X` with `X.yml` next to it. `X.yml`
  and `X.md` belong to `X` and are not documents themselves. A file in the
  intake with no sidecar (one dropped in by hand) is ingested first, as
  `ingest` would. Subdirectories of the intake, such as `archive/`, are
  never touched: giving one, or a file in one, as the path is an error.
- Files are handled one at a time, in name order, from a list taken before
  anything moves.

Other rules:

- A document that already has `results.transcribe` isn't transcribed again
  (status `Already transcribed 1 file`, nothing on stdout). There is no
  option to transcribe it again.
- If `X.md` already exists and its `sha256` matches the file, nothing is
  sent to the model: the existing transcript is used and recorded in
  `results.transcribe`.
- `--only` transcribes only documents that are already ingested. Any other
  file is left where it is, with a note on stderr
  (`Skipped FILE: not ingested yet`), and counted in the status as
  `Skipped 1 file (not ingested)`.
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
filez4eva classify ~/Scans
```

`classify` works on documents in the [intake](#intake), and selects them
the same way as [`transcribe`](#transcribing-files): the path can be a file,
a directory (top level only), or left out for every document in the intake.
A file that hasn't been [ingested](#ingesting-files) or
[transcribed](#transcribing-files) yet goes through those stages first, so
after `filez4eva classify ~/Scans` every file that was in `~/Scans` is in the
intake with its transcript `X.md` and its sidecar `X.yml`. `classify` never
prompts, so you can start it and walk away.

The model is given the transcript, along with the file's original name and
source (`results.ingest.original-name` and `results.ingest.source`). The
result is recorded under `results.classify` in the document's
[sidecar](#the-xyml-sidecar):

```yaml
results:
  ingest: ...
  transcribe: ...
  classify:
    at: '2026-10-25T14:03:09-07:00'
    model: claude-haiku-4-5
    cabinet: accounts
    doctype: receipt
    summary: Amazon.ca order receipt for a USB hub
    data:
      account: amazon
      date: '20261002'
      title: usb-hub-receipt
```

- `cabinet` is the [cabinet](#cabinets) the document is classified for (see
  below).
- `data` holds a value for each of the cabinet's [fields](#fields), in
  pattern order (here the pattern is `{account}/{date}-{title}`).
- `date` is the document's own date, as YYYYMMDD. If the document has no
  date of its own (or the model can't tell what it is), `date` is `null`
  rather than a guess. Today's date and the file's modified time are never
  used.
- Every other field is normalized to hyphen-separated-lower (see
  [Stowing a file with input data](#stowing-a-file-with-input-data)).
- `doctype` is one of the configured [doctypes](#classification-settings),
  or `other`.
- `summary` is a single line.
- The model is told the cabinet's `description` and each field's `guidance`
  (see [Fields](#fields)). For fields with
  [learned values](#learned-values), it is also given the common values
  (the same ones offered by tab completion) and asked to reuse one when it
  fits. It is also given the doctype names and descriptions.

The cabinet is chosen without asking:

- `--cabinet NAME` (or `-c NAME`) applies to every document in the run. An
  unknown name is an error before any file is touched.
- Without `--cabinet`, if only one cabinet is configured, it is used.
- Without `--cabinet`, if several cabinets are configured, the model picks
  one from the cabinet names and descriptions, then fills in that cabinet's
  fields. A pick that isn't a configured cabinet is a failure for that
  document (see below).

For each document it classifies, `classify` prints the document's path in
the intake on stdout. The status on stderr counts the files, e.g.
`Ingested 3 files | Transcribed 3 files | Classified 3 files`.

Other rules:

- A document that already has `results.classify` isn't classified again
  (status `Already classified 1 file`). There is no option to classify it
  again.
- `--only` classifies only documents that are already ingested and
  transcribed. Any other file is left as it is, with a note on stderr
  (`Skipped FILE: not ingested yet` or `Skipped FILE: not transcribed yet`),
  and counted in the status, e.g. `Skipped 1 file (not transcribed)`.
- If a document fails (transcription or classification fails, the model's
  answer is missing a field, has a field value with no letters or digits,
  or has an unknown doctype or cabinet, or the sidecar can't be read), the
  error is reported on stderr and the run carries on with the next file.
  The document gets no `results.classify`, so a later run tries it again.
  At the end, the documents that were classified are printed and
  `classify` exits non-zero. This also applies to a single file. A date
  that isn't a valid YYYYMMDD date becomes `null` instead of an error.
- The whole configuration (cabinets and doctypes) is checked before any file
  is touched.

Nothing is stowed: the document stays in the intake.

### Reviewing Files

To confirm or edit the proposed records of classified documents:

```bash
filez4eva review
```

`review` works on documents in the [intake](#intake), and selects them the
same way as [`transcribe`](#transcribing-files): the path can be a file, a
directory (top level only), or left out for every document in the intake.
A file that hasn't been [ingested](#ingesting-files),
[transcribed](#transcribing-files) or [classified](#classifying-files) yet
goes through those stages first. So the usual flow is
`filez4eva classify ~/Scans` (unattended), then `filez4eva review`.

For each document, `review` shows its name (and original name), then the
proposed record from `results.classify`: the summary, doctype, cabinet and
the value of each field (`(none)` for a document without a date). Then
choose:

- Confirm (c): prompts for each field are pre-filled with the proposed
  values. Press Enter to accept a value, or type a new one; tab completion
  offers the [learned values](#learned-values) of the field. With more than one cabinet configured, a
  `Cabinet:` prompt comes first, pre-filled with the proposed cabinet (see
  below). The confirmed record is saved as `results.review` and the
  document's path is printed on stdout.
- Skip (x): the document is left in the intake as it is, and a later run
  offers it again.
- Preview (p): opens the document with the `preview` command, then asks
  again.
- Delete (d): asks `Delete? [No] (Y)es` and, on `Y`, removes the document,
  its transcript `X.md` and its sidecar `X.yml`.
- Quit (q): ends the run. This document and the rest are left as they are.

An invalid value is rejected and the prompt asks again. Empty input at any
prompt goes back to the choice for the same document, without saving
anything.

Changing the cabinet: when several cabinets are configured, the `Cabinet:`
prompt accepts any configured cabinet (tab completion offers the names); an
unknown name is rejected and the prompt asks again. The field prompts that
follow are the chosen cabinet's fields. A field with the same name as one in
the proposed record (such as `date`) is pre-filled with its proposed value;
any other field starts empty. With a single cabinet there is no `Cabinet:`
prompt, and that cabinet is used. `results.classify` is never changed.

The status on stderr counts the files, e.g.
`Reviewed 2 files | Skipped 1 file | Deleted 1 file`, with `Quit` at the end
if you quit.

Other rules:

- A document that already has `results.review` isn't offered again (status
  `Already reviewed 1 file`).
- `--only` reviews only documents that are already ingested, transcribed
  and classified. Any other file is left as it is, with a note on stderr
  (e.g. `Skipped FILE: not classified yet`), and counted in the status, e.g.
  `Skipped 1 file (not classified)`.
- If a document fails (an earlier stage fails, its `results.classify` can't
  be used, or its sidecar can't be read), the error is reported on stderr
  and the run carries on with the next file. At the end, the documents that
  were reviewed are printed and `review` exits non-zero.
- The whole configuration (cabinets and doctypes) is checked before any file
  is touched.

Nothing is stowed: the document stays in the intake. To review and stow in
one pass, use [`stow`](#stowing-files).

### Stowing Files

To review and stow every document in the intake:

```bash
filez4eva stow
```

`stow` selects documents the same way as [`transcribe`](#transcribing-files):
the path can be a file, a directory (top level only), or left out for every
document in the [intake](#intake). A file that hasn't been
[ingested](#ingesting-files), [transcribed](#transcribing-files),
[classified](#classifying-files) or [reviewed](#reviewing-files) yet goes
through those stages first. So the main use case is:

```bash
filez4eva classify ~/Scans   # unattended: ingest, transcribe, classify
filez4eva stow               # interactive: confirm or edit, then stow
```

To review and stow every file in a directory in one interactive pass, give
the directory: `filez4eva stow ~/Scans`.

For each document that hasn't been reviewed, `stow` shows the proposed
record and offers the same choices as [`review`](#reviewing-files): confirm
(or edit), skip, preview, delete or quit. A confirmed document is stowed
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
   file is moved back. The values of fields with
   [learned values](#learned-values) are then recorded.
2. records `results.stow` in its sidecar `X.yml`: when it was stowed and
   where the file went (see [The X.yml sidecar](#the-xyml-sidecar)).
3. moves `X.yml` to `<intake>/archive/`, for later reference.

The absolute destination path is printed on stdout, so a script can
capture it, e.g.
`dest=$(filez4eva stow -d 20240213 -f title=receipt file.pdf)`.

- The cabinet and field values come from `results.review`, so a cabinet
  changed at review is the one used, not the one in `results.classify`.
- An existing file is never overwritten. If something already exists where
  the file, its transcript or its archived `X.yml` would go, the document
  fails before anything moves and stays in the intake.
- `--only` stows only documents already ingested, transcribed, classified
  and reviewed. Any other file is left as it is, with a note on stderr
  (e.g. `Skipped FILE: not reviewed yet`), and counted in the status, e.g.
  `Skipped 1 file (not reviewed)`. So `filez4eva review` followed by
  `filez4eva stow --only` stows without any prompts.
- If a document fails, the error is reported on stderr and the run carries
  on with the next file. At the end, the documents that were stowed are
  printed and `stow` exits non-zero. If the file was stowed but its sidecar
  couldn't be archived, the error says where the file went.
- The whole configuration (cabinets and doctypes) is checked before any file
  is touched.

The status on stderr counts the files, e.g.
`Reviewed 2 files | Stowed 3 files | Skipped 1 file`, with `Quit` at the end
if you quit.

#### Stowing a file with input data

For scripts and other tools that already know the record for a file, and
for filing a file by hand without asking the model, `stow` takes input data:
the `--cabinet` (or `-c`) and `--date` (or `-d`) flags, a repeatable
`--field NAME=VALUE` (or `-f NAME=VALUE`) for each other field, and a YAML
record on stdin with the cabinet and the fields under `data:`. For example,
for a cabinet whose pattern is `{date.year}/{account}/{date}_{part}`:

```bash
filez4eva stow -d 20240213 -f account=royal-bank -f part=visa \
  ~/Desktop/statement.pdf

printf 'cabinet: accounts\ndata:\n  date: 2024-02-13\n  account: royal-bank\n  part: visa\n' \
  | filez4eva stow ~/Desktop/statement.pdf
```

Input data is supplied when any of the flags is given, or stdin has a
`cabinet` or `data`. With input data:

- The path must be a single file. A directory, or no path (the intake), is
  an error before anything moves: `Input data (--cabinet, --date, --field or
  a record on stdin) needs a single file, ...`.
- The file is [ingested](#ingesting-files) and
  [transcribed](#transcribing-files) first if it hasn't been, as usual.
  `classify` and `review` are skipped: no model is asked for a record and no
  review menu is shown.
- Anything missing is prompted for, before any file is touched: the cabinet
  (only if several are configured; tab completion offers the names), then
  each of the cabinet's [fields](#fields) in pattern order, with tab
  completion of [learned values](#learned-values). An invalid value typed
  at a prompt is rejected and the prompt asks again; empty input cancels
  without moving anything. A complete record never prompts. So to file a
  document by hand, give just its cabinet, e.g.
  `filez4eva stow -c default ~/Desktop/statement.pdf` (`default` is the name
  of the single cabinet when no `cabinets` are configured), and type the
  rest.
- The record is saved as `results.review`, with `input: true` (see
  [The X.yml sidecar](#the-xyml-sidecar)), and the file is stowed with it
  exactly as above. `results.classify` isn't written. A document already in
  the intake with a `results.review` gets the supplied record instead.
  The record is saved only once the file has moved: if the stow fails (for
  example, a file with that name is already in the cabinet), the sidecar
  keeps what it had, so the document stays transcribed (or keeps its
  earlier review) and a later `stow` treats it as usual.
- An unknown cabinet or field, or an invalid date or value, from a flag or
  stdin is an error before anything moves.

The flags and stdin:

- Flags win over stdin.
- `--date` must be YYYYMMDD, e.g. `20240213`. On stdin, `date` may be
  `20240213`, `'20240213'` or `2024-02-13`.
- `--field` names must be fields of the chosen cabinet; anything else is an
  error. Use `--date`, not `--field date=...`, for the date.
- On stdin, the recognised keys are `cabinet` and `data`; any other
  top-level keys are ignored. Under `data`, keys that aren't fields of the
  chosen cabinet are ignored.
- Stdin that is empty, isn't valid YAML, isn't a mapping, or has neither a
  `cabinet` nor `data` is ignored (so `stow` runs as usual). A `data` value
  that isn't a mapping is an error.
- Values on stdin are read as plain text, so `0123` stays `0123` and `yes`
  stays `yes`. `~` and `null` are treated as missing, so that value is
  prompted for.

However the values are supplied (flags, stdin, prompts or the AI), every
field other than `date` ends up hyphen-separated-lower: accents are
stripped, letters are lowercased, and each run of anything other than `a-z`
and `0-9` becomes a single hyphen, trimmed at both ends. So
`Royal Bank of Canada` becomes `royal-bank-of-canada`, and the value can
never contain `/` or `..`. A value with nothing left (such as `../`) is
rejected: from a flag or stdin, `stow` exits with an error; typed at a
prompt, the prompt asks again. A normalized value typed at a prompt is used
without asking again.

### Command Line Options

`filez4eva --help` lists the commands, and `filez4eva COMMAND --help`
describes a command and its options.

Global options:
- `--config PATH`: Specify path to config file
- `--debug`: Enable debug output

ingest command:
- `--meta, -m KEY=VALUE`: Record source metadata (repeatable)
- `path`: Path to the file, or directory of files, to ingest

transcribe command:
- `--only`: Transcribe only documents already ingested; skip other files
- `path`: Optional file or directory to transcribe (defaults to the intake)

classify command:
- `--cabinet, -c NAME`: Classify every document for this cabinet
- `--only`: Classify only documents already ingested and transcribed; skip
  other files
- `path`: Optional file or directory to classify (defaults to the intake)

review command:
- `--only`: Review only documents already ingested, transcribed and
  classified; skip other files
- `path`: Optional file or directory to review (defaults to the intake)

stow command:
- `--only`: Stow only documents already ingested, transcribed, classified
  and reviewed; skip other files (with input data: ingested and transcribed)
- `--cabinet, -c NAME`: Input data: the cabinet to stow into
- `--date, -d DATE`: Input data: the date, in YYYYMMDD format
- `--field, -f NAME=VALUE`: Input data: the value of a field (repeatable)
- `path`: Optional file or directory to stow (defaults to the intake); a
  single file with input data (flags or a record on stdin; see
  [Stowing a file with input data](#stowing-a-file-with-input-data))

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
it. It is set with the optional `intake` key:

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

`classify` adds:

```yaml
results:
  ingest: ...
  transcribe: ...
  classify:
    at: '2026-10-25T14:03:15-07:00'
    model: claude-haiku-4-5
    cabinet: accounts
    doctype: receipt
    summary: Amazon.ca order receipt for a USB hub
    data:
      date: '20261002'
      title: usb-hub-receipt
```

- `at`: when the document was classified, in ISO-8601 local time with its
  UTC offset, to the second.
- `model`: the model that classified it.
- `cabinet`, `doctype`, `summary` and `data`: the classification (see
  [Classifying Files](#classifying-files)). `data` has a value for each of
  the cabinet's fields, in pattern order, with `date` as YYYYMMDD or
  `null`.

`review` adds, when you confirm the record:

```yaml
results:
  ingest: ...
  transcribe: ...
  classify: ...
  review:
    at: '2026-10-25T15:20:41-07:00'
    cabinet: accounts
    data:
      date: '20261002'
      title: usb-hub-receipt
```

- `at`: when the record was confirmed, in ISO-8601 local time with its UTC
  offset, to the second.
- `cabinet`: the confirmed cabinet, which may differ from
  `results.classify.cabinet` (see [Reviewing Files](#reviewing-files)).
- `data`: the confirmed value of each of that cabinet's fields, in pattern
  order, with `date` as YYYYMMDD.

When `stow` is given [input data](#stowing-a-file-with-input-data), it
writes `results.review` itself, in the same shape, with `input: true`, and
there is no `results.classify`:

```yaml
results:
  ingest: ...
  transcribe: ...
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

- A value is recorded only when `stow` actually moves a file into the
  cabinet, wherever the value came from (the model, a review, flags, stdin
  or a prompt). `classify` and `review` record nothing, and existing files
  aren't scanned, so the list starts empty.
- Tab completion, and the AI model, are offered values used at least twice,
  most-used first, at most 100 per field. A value used once is remembered,
  but only offered once it is used again.
- You can seed or prune the list by editing the file. Values that aren't
  hyphen-separated-lower are never offered.
- The file is written to a temporary file and renamed, so a synced target
  never sees a half-written file. If it can't be read or written, the file
  is still stowed, a warning is shown, and the existing file is left as it
  was.

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

How a document's cabinet is chosen:

- `classify` never asks: it uses `--cabinet NAME` (or `-c NAME`), the only
  cabinet, or the model's pick. See [Classifying Files](#classifying-files).
- `review` (and `stow`, for a document not yet reviewed) lets you change
  the cabinet before confirming: see [Reviewing Files](#reviewing-files).
- `stow` with [input data](#stowing-a-file-with-input-data) uses
  `--cabinet NAME` (or `-c NAME`) or a `cabinet` key on stdin; the flag wins
  if both are given. If neither is given and there is more than one
  cabinet, it prompts for one, with tab-completion of the names.
- With only one cabinet, it is used without asking.
- An unknown name from a flag or stdin is an error; an unknown name typed at
  a prompt is rejected and the prompt asks again.

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
| `filez4eva stow-file FILE` with `--cabinet`, `--date`, `--field NAME=VALUE` or a record on stdin | `filez4eva stow FILE` with the same flags or stdin record. See [Stowing a file with input data](#stowing-a-file-with-input-data). |
| `filez4eva stow-file FILE`, typing every value at the prompts | `filez4eva stow FILE` to have the model propose the values, which you confirm or edit; or `filez4eva stow -c CABINET FILE` to type them yourself, as before. |
| `filez4eva scan-dir DIR`, or `filez4eva` on its own with `source:` configured | `filez4eva classify DIR` (unattended), then `filez4eva stow`; or `filez4eva stow DIR` for one interactive pass. The menu offers confirm, skip, preview, delete and quit. |
| `filez4eva process FILE` | `filez4eva stow FILE`: it transcribes and classifies the file, asks you to confirm or edit the record, then stows it. |
| `filez4eva process --cabinet NAME FILE` | `filez4eva classify --cabinet NAME FILE`, then `filez4eva stow`. |
| `filez4eva process --dry-run FILE` | `filez4eva review FILE`, which saves the confirmed record without moving the file into a cabinet; then `filez4eva stow`. |

Differences to be aware of:

- Every file now goes through the [intake](#intake) on its way to a
  cabinet: it is moved there and renamed when it is ingested, and its
  transcript `X.md` is written there, rather than next to the original
  file. Where it ends up in the cabinet is the same as before.
- `stow FILE` transcribes the file before stowing it, even with input data,
  so it needs an Anthropic API key (see
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
