# Filez4Eva

⚠️ DISCLAIMER: This is a hobby/personal project. Not a commercial product. Not for production use.

## Rename and stow files with structured patterns

The following document is for _developers_ contributing to the application. For information about how to _use_ the application, see [PACKAGE.md](PACKAGE.md).

## Development setup

Requires Python 3.14 or higher. Uses [Dyngle](https://dyngle.steamwiz.io/) for administration (installed separately). Shared Dyngle operations live in the `.conf` submodule ([SteamWiz/Conf](https://github.com/SteamWiz/Conf)), so clone with `--recurse-submodules` or run `git submodule update --init`.

- `dyngle run init` - Create the virtual environment and install poetry
- `dyngle run dependencies` - Install the required packages using poetry
- `dyngle run test` - Run tests and report coverage (same as CI/CD)
- `dyngle run style` - Run style checks
- `dyngle run build` - Create a test build
- `dyngle run sandbox` - Reset the sandbox directories for manual testing

GitHub Actions performs the entire build/test/release cycle using the shared [SteamWiz actions](https://github.com/SteamWiz/actions).

## Intake and sidecars

`filez4eva ingest` moves files into the intake and writes an `X.yml` sidecar next to each one (see [PACKAGE.md](PACKAGE.md#ingesting-files)). The helpers for intake names and sidecars (`intake_dir`, `extensions`, `stamp_name`, `stamp_taken`, `sidecar_path`, `in_intake`, `is_ingested`, `read_sidecar`, `write_sidecar`) are module-level functions in `filez4eva/command/ingest_command.py`, for later stages to reuse. X/X.yml pairing (`is_ingested`, `is_companion`) only counts for files whose parent is the intake (`in_intake`). Stamp check-and-claim (`reserve`) runs under `intake_lock(intake)`, an exclusive `fcntl.flock` on the intake directory, so concurrent `ingest` processes on one machine never share a stamp. `Filez4EvaCommand.stdin_mapping()` reads a YAML mapping piped on stdin, for any command. Tests patch `ingest_command.now` to freeze the clock.

## Stage commands

The shared logic for the stage commands lives in `filez4eva/stage.py`, for `transcribe` now and `classify`, `review` and `stow` later. `resolve_path` turns the optional path argument into a path (none = the intake; subdirectories of the intake such as `archive/` are refused). `documents` selects the documents: a file on its own, or the non-hidden regular files at the top level of a directory, where in the intake the `X.yml`/`X.md` companions of a document `X` are left out. `load_sidecar`, `stage_result` and `record_result` read and write `results.<stage>` in `X.yml`, refusing to overwrite a sidecar that can't be read. `StageCommand` adds `--only` and the optional `path`, and its `run()` applies the prerequisite rule (ingest first, or skip with a note under `--only`), skips documents that already have `results.<stage>`, reports per-file errors and carries on, and raises at the end if any failed. A subclass sets `name`, `stage` and `done` and implements `act(path)`.

`transcribe_file` in `transcribe_command.py` is the in-place transcription with the sha256 cache. `classify` (and so `process` and `scan-dir`) calls it directly, so those commands never ingest or move files. `write_atomically` lives in `filez4eva/atomic.py`. Stage tests set `FILEZ4EVA_INTAKE` to a temporary directory as well as the config, so no test can touch the real intake.

## Libraries

The application uses the following external libraries:

- [WizLib](https://wizlib.steamwiz.io/) for CLI and configuration handling
- [Kwark](https://github.com/SteamWiz/Kwark) (its `kwark.ai` library layer) for transcribing files to Markdown and classifying them with Claude. Filez4Eva passes its own settings (model, API key) as arguments and never reads Kwark's configuration. Tests mock `kwark.ai.transcribe` and `kwark.ai.extract`, so no API calls are made.

Note that this application makes heavy use of WizLib and all code changes are expected to comply with, and take advantage of, the framework.
