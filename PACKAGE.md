# Filez4Eva

⚠️ DISCLAIMER: This is a hobby/personal project. Not a commercial product. Not for production use.

## Shift scans, photos, and other files into structured folders for permanent safekeeping

Filez4Eva is a command-line tool that helps you organize files by naming them correctly and placing them in the right directory structure. It's especially useful for managing account documents, scanned files, and other personal records.

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
- Date in YYYYMMDD format
- Account name (with tab-completion from existing accounts)
- Part name (with tab-completion from existing files for that account)

Values can also be piped in as a YAML mapping on stdin, which is handy for
other tools that produce a record for the file:

```bash
printf 'date: 20240213\naccount: acct\npart: statement\n' \
  | filez4eva stow-file ~/Desktop/statement.pdf
```

- Recognised keys are `cabinet`, `date`, `account` and `part`; any other keys
  are ignored.
- Command-line flags override values from stdin.
- Anything still missing is prompted for as usual.
- `date` may be `20240213`, `'20240213'` or `2024-02-13`. If it isn't a valid
  date, `stow-file` exits with an error.
- If stdin is empty, isn't valid YAML, or isn't a mapping, it is ignored.
- Values are read as plain text, so `0123` stays `0123` and `yes` stays `yes`.
- `~` and `null` are treated as missing, so that value is prompted for.
- Stdin is only read by `stow-file` itself. `scan-dir` ignores it.

However the values are supplied (flags, stdin or prompts), `account` must be a
single directory name (not empty, `.` or `..`, and without `/` or `\`), and
`part` may contain only letters, digits and hyphens. An invalid value from a
flag or stdin makes `stow-file` exit with an error. An invalid value typed at
a prompt is rejected and the prompt asks again.

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

### Command Line Options

Global options:
- `--config PATH`: Specify path to config file
- `--debug`: Enable debug output

stow-file command:
- `--cabinet, -c NAME`: Specify the cabinet (destination) to stow into
- `--date, -d DATE`: Specify date in YYYYMMDD format
- `--account, -a ACCOUNT`: Specify account name
- `--part, -p PART`: Specify part name
- `file`: Path to the file to stow

After a successful move, `stow-file` prints the absolute destination path on
stdout (the `Done` status goes to stderr), so scripts can capture it, e.g.
`dest=$(filez4eva stow-file -d 20240213 -a acct -p part file.pdf)`.

scan-dir command:
- `dir`: Optional path to directory to scan (defaults to configured source)

## Configuration

Create a `filez4eva.yml` file with:

```yaml
filez4eva:
  source: '~/Desktop'          # Default source directory
  target: '~/Dropbox/accounts' # Target directory for stowed files
```

Files will be organized in this pattern:
```
~/Dropbox/accounts/<year>/<account>/<date>-<part>.<extension>
```

### Destination pattern

The layout under `target` can be changed with the optional `pattern` key:

```yaml
filez4eva:
  target: '~/Dropbox/accounts'
  pattern: '{account}/{year}/{part}-{date}{ext}'
```

The default is `'{year}/{account}/{date}-{part}{ext}'`, which gives the layout
shown above. Quote the pattern in YAML, since it starts with `{`.

Placeholders:
- `{year}`: four-digit year, e.g. `2024`
- `{date}`: date as YYYYMMDD, e.g. `20240213`
- `{account}`: account name
- `{part}`: part name
- `{ext}`: the source file's extension, including the dot (e.g. `.pdf`), or
  nothing if the file has no extension

Use `/` to create subdirectories; missing directories are created. Any other
text is used literally. A pattern is a configuration error, and `stow-file`
exits before moving anything or prompting, if it:
- uses a placeholder not listed above, or a positional one like `{}` or `{0}`
- uses format specs, conversions, attributes or indexes (e.g. `{year:>4}`,
  `{account!r}`, `{year.x}`, `{account[0]}`)
- has unbalanced braces
- is absolute, starts with `~`, or contains `..`

Tab completion of accounts and parts reads existing files in the default
layout, so it only works with the default pattern. With any other pattern the
prompts still accept typed values but offer no completion.

### Cabinets

To file into more than one destination, configure named cabinets:

```yaml
filez4eva:
  cabinets:
    accounts:
      target: ~/Dropbox/accounts
      pattern: '{year}/{account}/{date}-{part}{ext}'
      description: Personal account records
    memories:
      target: ~/Dropbox/memories
      pattern: '{account}/{year}/{part}-{date}{ext}'
```

Each cabinet has:
- `target` (required): the directory files are stowed under
- `pattern` (optional): the layout under the target, as described above.
  Defaults to the top-level `pattern` if set, otherwise
  `'{year}/{account}/{date}-{part}{ext}'`
- `description` (optional): a note on what the cabinet holds

Choose the cabinet with `--cabinet NAME` (or `-c NAME`), or with a `cabinet`
key on stdin; the flag wins if both are given. If neither is given and there
is more than one cabinet, `stow-file` prompts for one, with tab-completion of
the names. With only one cabinet it is used without asking. An unknown name
from the flag or stdin is an error; an unknown name typed at the prompt is
rejected and the prompt asks again. `scan-dir` asks for a cabinet for each
file it stows.

Tab completion of accounts and parts reads the chosen cabinet's target.

If there is no `cabinets` section (or it is empty), the top-level `target` and
`pattern` form a single cabinet named `default`, so existing configurations
work unchanged. If `cabinets` is present, the top-level `target` is ignored.

The whole configuration is checked before any prompt: a cabinet with no
`target`, or with an invalid pattern, is an error even if it isn't the one
being used.
