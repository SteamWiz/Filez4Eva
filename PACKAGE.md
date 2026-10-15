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

### Stowing Individual Files

To organize a single file (like a downloaded PDF):

```bash
filez4eva stow-file ~/Desktop/123456789SomeFileIDownloaded.pdf
```

Filez4Eva will interactively prompt for:
- Cabinet, only if several are configured (with tab-completion of cabinet
  names; see [Cabinets](#cabinets))
- Each of the cabinet's [fields](#fields), in the order they appear in its
  pattern. With the default pattern, `{date}-{title}`, that is the date (in
  YYYYMMDD format) and then a title. Fields with
  [learned values](#learned-values) offer tab-completion of the common ones.

Field values can be given on the command line with `--date` and a repeatable
`--field NAME=VALUE` (or `-f NAME=VALUE`). For example, for a cabinet whose
pattern is `{date.year}/{account}/{date}_{part}`:

```bash
filez4eva stow-file -d 20240213 -f account=royal-bank -f part=visa \
  ~/Desktop/statement.pdf
```

Values can also be piped in as a YAML mapping on stdin, which is handy for
other tools that produce a record for the file (such as
[`classify`](#classifying-files)). The fields go under `data:`:

```bash
printf 'data:\n  date: 20240213\n  title: visa-statement\n' \
  | filez4eva stow-file ~/Desktop/statement.pdf
```

- Recognised keys are `cabinet` and `data`; any other top-level keys are
  ignored. Under `data`, keys that aren't fields of the chosen cabinet are
  ignored.
- Command-line flags override values from stdin.
- Anything still missing is prompted for as usual.
- `date` may be `20240213`, `'20240213'` or `2024-02-13`. If it isn't a valid
  date, `stow-file` exits with an error.
- If stdin is empty, isn't valid YAML, or isn't a mapping, it is ignored. A
  `data` value that isn't a mapping is an error.
- Values are read as plain text, so `0123` stays `0123` and `yes` stays `yes`.
- `~` and `null` are treated as missing, so that value is prompted for.
- Stdin is only read by `stow-file` itself. `scan-dir` ignores it.

However the values are supplied (flags, stdin, prompts or the AI), every
field other than `date` ends up hyphen-separated-lower: accents are
stripped, letters are lowercased, and each run of anything other than `a-z`
and `0-9` becomes a single hyphen, trimmed at both ends. So
`Royal Bank of Canada` becomes `royal-bank-of-canada`, and the value can
never contain `/` or `..`. A value with nothing left (such as `../`) is
rejected: from a flag or stdin, `stow-file` exits with an error; typed at a
prompt, the prompt asks again. A normalized value typed at a prompt is used
without asking again.

`--field` names must be fields of the chosen cabinet; anything else is an
error. Use `--date`, not `--field date=...`, for the date.

### Processing Multiple Files

To process all files in a directory:

```bash
filez4eva scan-dir ~/Desktop
```

This interactive process lets you:
- Skip a file (x)
- Preview a file (p)
- Stow a file (s)
- Delete a file (d)
- Quit processing (q)

Stowing a file works like [`process`](#processing-a-file-with-ai): the file
is transcribed (reusing an up-to-date transcript) and classified, then the
summary and doctype are shown and a prompt for each of the cabinet's fields
is pre-filled with the proposed value (the `Date:` prompt starts empty if
the document has no date of its own). Press Enter to accept a value, or
type a new one. With several cabinets, the cabinet is asked for once, before
anything is sent to the model.

- If transcription or classification fails (for example, no API key or an
  unsupported file type), the error is shown and the prompts start empty, as
  they would without AI.
- Empty input at any prompt returns to the action choice for the same file,
  without moving anything.

Transcripts written by `transcribe` are not offered as files of their own:
`X.md` is skipped when `X` is in the same directory (for example
`scan.pdf.md` next to `scan.pdf`). A `.md` file with no such companion is
offered as usual. Deleting a file also deletes its transcript. Stowing a file
moves its transcript with it (see [stow-file](#command-line-options)).

### Transcribing Files

To transcribe a file to Markdown using an AI model:

```bash
filez4eva transcribe ~/Desktop/scan.pdf
```

This writes `scan.pdf.md` next to the file (the full file name plus `.md`)
and prints its path on stdout. The transcript looks like:

```markdown
---
source: scan.pdf
sha256: 3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b
model: claude-opus-4-6
transcribed: '2026-10-10T17:42:05+00:00'
---
<!-- Generated by an AI process from a binary file. ... -->

...Markdown transcription...
```

- Supported file types are PDF, PNG, JPEG, GIF, WebP, plain text, Markdown
  and CSV.
- If the transcript already exists and its `sha256` matches the file, nothing
  is sent to the model and the existing path is printed (status `Unchanged`
  on stderr). If the file has changed, or the transcript has no readable
  front matter, it is transcribed again and overwritten.
- `--force` (or `-f`) transcribes again even if the transcript is up to date.
- If transcription fails (e.g. an unsupported file type or an API error),
  `transcribe` exits with an error and any existing transcript is left as it
  was.

See [Transcription settings](#transcription-settings) for the model and API
key.

### Classifying Files

To have an AI model propose where a file should be filed:

```bash
filez4eva classify ~/Desktop/scan.pdf
```

`classify` transcribes the file first if needed (exactly as `transcribe`
does, reusing an up-to-date transcript), then asks the model to classify the
transcript and prints a YAML record on stdout:

```yaml
file: /Users/me/Desktop/scan.pdf
transcript: /Users/me/Desktop/scan.pdf.md
cabinet: accounts
doctype: receipt
summary: Amazon.ca order receipt for a USB hub
data:
  account: amazon
  date: '20261002'
  title: usb-hub-receipt
```

- `data` holds a value for each of the cabinet's [fields](#fields), in
  pattern order (here the pattern is `{account}/{date}-{title}`).
- `date` is the document's own date, as YYYYMMDD. If the document has no
  date of its own (or the model can't tell what it is), `date` is `null`
  rather than a guess. Today's date and the file's modified time are never
  used.
- Every other field is normalized to hyphen-separated-lower, as for
  `stow-file`.
- `doctype` is one of the configured [doctypes](#classification-settings),
  or `other`.
- `summary` is a single line.
- The model is told the cabinet's `description` and each field's `guidance`
  (see [Fields](#fields)). For fields with
  [learned values](#learned-values), it is also given the common values
  (the same ones offered by tab completion) and asked to reuse one when it
  fits. It is also given the doctype names and descriptions.
- The cabinet is chosen as for `stow-file`: `--cabinet NAME`, the only
  cabinet, or a prompt.
- If transcription or classification fails, or the model's answer is
  missing a field, has a field value with no letters or digits, or has an
  unknown doctype, `classify` exits with an error and prints nothing on
  stdout. A date that isn't a valid YYYYMMDD date becomes `null` instead of
  an error.

Nothing is moved. To file the document as proposed, pipe the record into
`stow-file`, which reads `cabinet` and `data` and ignores the other keys:

```bash
filez4eva classify ~/Desktop/scan.pdf | filez4eva stow-file ~/Desktop/scan.pdf
```

If the record has `date: null`, `stow-file` prompts for the date.

### Processing a File with AI

To transcribe, classify, confirm and stow a file in one go:

```bash
filez4eva process ~/Desktop/scan.pdf
```

`process`:
1. transcribes the file if needed (as `transcribe` does, reusing an
   up-to-date transcript)
2. classifies it (as `classify` does)
3. shows the summary and doctype, then prompts for `Cabinet:` (only if
   several cabinets are configured and it wasn't just chosen) and then each
   of the cabinet's fields in pattern order, each pre-filled with the
   proposed value. Press Enter to accept it, or type a new value (backspace
   clears the pre-filled value first). If the classification has no date,
   the `Date:` prompt starts empty. If you change the cabinet, only fields
   with the same name in the new cabinet are pre-filled. Tab completion
   works as for `stow-file`.
4. stows the file and its transcript, exactly as `stow-file` does, and prints
   the destination path on stdout

- Confirmation is always interactive.
- Empty input at any prompt cancels without moving anything. An invalid value
  is rejected and the prompt asks again.
- The cabinet is chosen as for `classify` (`--cabinet NAME`, the only
  cabinet, or a prompt) before anything is sent to the model, and the whole
  configuration is checked first.
- `--dry-run` transcribes, classifies and prompts as usual, then prints where
  the file (and its transcript) would go, without moving anything.

### Command Line Options

Global options:
- `--config PATH`: Specify path to config file
- `--debug`: Enable debug output

stow-file command:
- `--cabinet, -c NAME`: Specify the cabinet (destination) to stow into
- `--date, -d DATE`: Specify date in YYYYMMDD format
- `--field, -f NAME=VALUE`: Specify the value of a field (repeatable)
- `file`: Path to the file to stow

After a successful move, `stow-file` prints the absolute destination path on
stdout (the `Done` status goes to stderr), so scripts can capture it, e.g.
`dest=$(filez4eva stow-file -d 20240213 -f title=receipt file.pdf)`.

If the file has a transcript (`FILE.md`, written by `transcribe`), `stow-file`
moves it too, named after the stowed file. By default it goes adjacent to the
stowed file: `.../20261002-receipt.pdf` gets `.../20261002-receipt.pdf.md`.
It can instead go into a parallel tree; see
[Transcript location](#transcript-location). If a transcript already exists at
its destination, `stow-file` fails before moving anything.

scan-dir command:
- `dir`: Optional path to directory to scan (defaults to configured source)

transcribe command:
- `--force, -f`: Transcribe again even if the transcript is up to date
- `file`: Path to the file to transcribe

classify command:
- `--cabinet, -c NAME`: Specify the cabinet to classify for
- `file`: Path to the file to classify

process command:
- `--cabinet, -c NAME`: Specify the cabinet to classify for and stow into
- `--dry-run`: Show where the file would go without moving anything
- `file`: Path to the file to process

## Configuration

Create a `filez4eva.yml` file with:

```yaml
filez4eva:
  source: '~/Desktop'          # Default source directory
  target: '~/Dropbox/accounts' # Target directory for stowed files
```

By default, files are stowed directly under the target, named after their
date and a title, keeping their extension:
```
~/Dropbox/accounts/<date>-<title>.<extension>
```

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
AI) in the order they first appear. Placeholders:
- `{date}`: the date as YYYYMMDD, e.g. `20240213`. Every pattern must
  contain `{date}`.
- `{date.year}`: the date's four-digit year, e.g. `2024`. It doesn't count
  as `{date}`.
- `{name}`: any other field, where `name` is lowercase letters, digits and
  underscores, starting with a letter (e.g. `{title}`, `{account}`,
  `{event}`). Its value is hyphen-separated-lower.

The source file's extension (e.g. `.pdf`) is always added to the end, so
don't put it in the pattern. Use `/` to create subdirectories; missing
directories are created. `{{` and `}}` are literal braces, and any other
text is used literally. Since field values contain hyphens, use another
separator such as `_` between two fields if you want to tell them apart
later.

A pattern is a configuration error, and `stow-file` exits before moving
anything or prompting, if it:
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

- A value is recorded only when `stow-file` (or `process` or `scan-dir`)
  actually moves a file, wherever the value came from. A dry run records
  nothing, and existing files aren't scanned, so the list starts empty.
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

Choose the cabinet with `--cabinet NAME` (or `-c NAME`), or with a `cabinet`
key on stdin; the flag wins if both are given. If neither is given and there
is more than one cabinet, `stow-file` prompts for one, with tab-completion of
the names. With only one cabinet it is used without asking. An unknown name
from the flag or stdin is an error; an unknown name typed at the prompt is
rejected and the prompt asks again. `scan-dir` asks for a cabinet for each
file it stows (once per file, before classifying it).

Prompts, tab completion and learned values use the chosen cabinet's fields
and target.

If there is no `cabinets` section (or it is empty), the top-level `target`,
`pattern` and `fields` form a single cabinet named `default`. If `cabinets`
is present, the top-level `target` is ignored.

The whole configuration is checked before any prompt: a cabinet with no
`target`, or with an invalid pattern, fields or transcripts setting, is an
error even if it isn't the one being used.

### Transcript location

When `stow-file` stows a file that has a transcript, the transcript goes
next to the stowed file by default (`adjacent`). To keep transcripts in a
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
mapping is a configuration error, and `stow-file` exits before prompting or
moving anything. An error in a top-level setting names the top level rather
than a cabinet. An empty `transcripts:` block, or an empty `location`, counts
as unset, but other values such as `no` or `0` are rejected as invalid
locations.

This only affects `stow-file`. `transcribe` and `scan-dir` always write the
transcript of an incoming file next to it, as `FILE.md`.

### Transcription settings

`transcribe` uses these optional keys:

```yaml
filez4eva:
  transcribe:
    model: claude-opus-4-6              # Anthropic model ID
  anthropic:
    key: $(op read op://vault/anthropic/credential)
```

- `transcribe: model:` defaults to `claude-opus-4-6`.
- `anthropic: key:` is the Anthropic API key. Like other values it may use
  `$(...)` to run a command, such as a password manager lookup. It can also
  be set with the `FILEZ4EVA_ANTHROPIC_KEY` environment variable, which takes
  precedence over the config file. If neither is set, the Anthropic SDK's own
  `ANTHROPIC_API_KEY` environment variable is used.

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

### Upgrading from version 5

Version 6 replaces the fixed `account` and `part` with fields named by each
cabinet's pattern:
- The default pattern is now `{date}-{title}`, directly under the target. To
  keep the old layout, set `pattern: '{date.year}/{account}/{date}-{part}'`.
- `{year}` is now `{date.year}`, and `{ext}` is no longer used: the
  extension is always added. In a version 6 pattern, `{year}` or `{ext}`
  would be an ordinary field that you are prompted for.
- `stow-file --account/-a` and `--part/-p` are replaced by `--field/-f
  NAME=VALUE`.
- In the `classify` record and `stow-file` stdin, the fields (including
  `date`) are under `data:`.
- Field values are normalized to hyphen-separated-lower, so existing
  directories with capitals or spaces won't match new values.
- Tab completion no longer scans existing folders; it offers
  [learned values](#learned-values) instead. Existing files are not moved.
