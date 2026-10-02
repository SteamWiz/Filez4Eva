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
- Date in YYYYMMDD format
- Account name (with tab-completion from existing accounts)
- Part name (with tab-completion from existing files for that account)

### Processing Multiple Files

To process all files in a directory:

```bash
filez4eva stow-dir ~/Desktop
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
- `--date, -d DATE`: Specify date in YYYYMMDD format
- `--account, -a ACCOUNT`: Specify account name
- `--part, -p PART`: Specify part name
- `file`: Path to the file to stow

stow-dir command:
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
