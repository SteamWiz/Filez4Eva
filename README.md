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

`filez4eva ingest` moves files into the intake and writes an `X.yml` sidecar next to each one (see [PACKAGE.md](PACKAGE.md#ingesting-files)). The helpers for intake names and sidecars (`intake_dir`, `extensions`, `stamp_name`, `stamp_taken`, `sidecar_path`, `in_intake`, `is_ingested`, `read_sidecar`, `write_sidecar`) are module-level functions in `filez4eva/command/ingest_command.py`, for later stages to reuse. X/X.yml pairing (`is_ingested`, `is_companion`) only counts for files whose parent is the intake (`in_intake`). Stamp check-and-claim (`reserve`) runs under `intake_lock(intake)`, an exclusive `fcntl.flock` on the intake directory, so concurrent `ingest` processes on one machine never share a stamp. `stdin_mapping(app)` in `filez4eva/command/__init__.py` (and `Filez4EvaCommand.stdin_mapping()`) reads a YAML mapping piped on stdin. Tests patch `ingest_command.now` to freeze the clock.

## Commands

There are five commands: `ingest`, `transcribe`, `classify`, `review` and `stow`. `Filez4EvaCommand.default` is `None`, so running `filez4eva` with no command gives WizLib's error for a missing command (`Unknown command None`), and an unknown name gives its `unrecognized arguments` error. Each command sets `summary` (its line in the list of commands that `Filez4EvaApp.initialize` adds to `filez4eva --help`, in the order of `Filez4EvaApp.commands`) and `description` (the text of `filez4eva COMMAND --help`); arguments have `help`. `test/test_app.py` covers the command set and the help.

## Stage commands

The shared logic for the stage commands lives in `filez4eva/stage.py`, for `transcribe`, `classify`, `review` and `stow`. `resolve_path` turns the optional path argument into a path, expanded and absolute but not resolved, so messages and output use paths as the user and the configuration give them (none = the intake; subdirectories of the intake such as `archive/` are refused, checked on the resolved path so a symbolic link can't get round it). `documents` selects the documents: a file on its own, or the non-hidden regular files at the top level of a directory, where in the intake the `X.yml`/`X.md` companions of a document `X` are left out. `load_sidecar`, `stage_result` and `record_result` read and write `results.<stage>` in `X.yml`, refusing to overwrite a sidecar that can't be read. `StageCommand` adds `--only` and the optional `path`, and its `run()` applies the prerequisite rule (ingest first, then each earlier stage in `requires` that the document lacks, by calling that command's `act`; or skip with a note under `--only`), skips documents that already have `results.<stage>`, reports per-file errors and carries on, and raises at the end if any failed. `run()` calls `handle_vals()` on each earlier stage command before any file is touched, so their configuration is checked up front. A subclass sets `name`, `stage`, `done` and `requires` (e.g. `ClassifyCommand.requires = (TranscribeCommand,)`) and implements `act(path)`. `act` can raise `NotDone(label)` to leave a document without the stage (counted in the status under the label, e.g. `Skipped`), or `StopRun` to end the run early (the status ends with `Quit`).

`ReviewCommand` (`requires = (TranscribeCommand, ClassifyCommand)`) is interactive: `act` shows `results.classify` and offers confirm/skip/preview/delete/quit (skip and delete raise `NotDone`, quit raises `StopRun`). Confirming uses `Stower.confirm_values` (see below): an optional pre-filled `Cabinet:` prompt, then the final cabinet's fields pre-filled from proposed values of the same name. `review` saves `results.review` and never touches `results.classify`. Review tests mock `wizlib.io.ttyin` for the menu keys and `app.ui.get_text` for the prompts.

`StowCommand` (`requires = (TranscribeCommand, ClassifyCommand, ReviewCommand)`) stows each document as soon as it has `results.review`, so in an interactive run every document is stowed straight after it's confirmed. `act` checks `results.review` (`confirmed`), builds a `Stower` with the reviewed cabinet, date and data (so it never prompts) and calls its `stow()`, the move-and-transcript logic (plan, never overwrite, roll back the file if the transcript can't move, record learned values). It then writes `results.stow` and moves `X.yml` to `archived_sidecar(path)`, `<intake>/archive/X.yml`, which it checks is free before anything moves. Ingest's `reserve` passes over a name whose sidecar is already archived, so a later document can always be archived. With input data (`--cabinet`, `--date`, `--field`, or a stdin record with a `cabinet` or `data`; see `input_supplied`), `handle_vals` checks that the path is a single file, then builds a `Stower` (with `use_stdin=True`) and calls its `read_values` and `field_values`, so flags win over stdin, missing values are prompted for, and every value is checked before anything moves. It keeps the result in `input_record` and sets `requires = (TranscribeCommand,)` on the instance, so `run()` skips classify and review; `act` then writes the record as `results.review` (with `input: true`) before stowing as usual. Its tests (`test/test_command_stow_stage.py`) reuse `ReviewTestCase` with `command_class = StowCommand`.

`filez4eva/stow.py` holds the cabinets (`Cabinet`, `load_cabinets`, transcript locations) and `Stower`, the stow logic for one file. `Stower` is a plain class, not a command, so it never shows up as one; it takes the app and the same values a command would (`file`, `cabinet`, `date`, `data`, `field`, `use_stdin`). `read_values` fills in the cabinet and fields from `--field` flags, then stdin (with `use_stdin`), then prompts; `confirm_values` confirms a proposed record at pre-filled prompts; `plan` works out the destinations without moving anything; `stow` moves the file and its transcript and records learned values. `test/test_stow.py` tests it directly, through `execute` (`read_values` then `stow`) and `start_stower` (the same with an app set up from a configuration file and the stow command's flags).

`ClassifyCommand` never prompts: it checks `--cabinet` and the configuration in `handle_vals`, before any file is touched, and with several cabinets and no `--cabinet` asks the model to pick one (`pick_cabinet`) before classifying for it (`classify_text`). `transcribe_file` in `transcribe_command.py` is the in-place transcription with the sha256 cache, used by `TranscribeCommand.act`. `write_atomically` lives in `filez4eva/atomic.py`. Stage tests set `FILEZ4EVA_INTAKE` to a temporary directory as well as the config, so no test can touch the real intake.

## Test isolation

`test/conftest.py` keeps results independent of the machine running the tests. For the whole run, temporary files (`tempfile`, so every `TemporaryDirectory`) live behind a symbolic link, as they do on macOS, where `/var` is a link to `/private/var`; a command that mixes resolved and unresolved paths fails on Linux CI too. Each test starts with no `FILEZ4EVA_*` environment variables, an empty `HOME` (no `~/.filez4eva.yml`, no `~/.filez4eva/intake`) and `FILEZ4EVA_CONFIG` pointing at an empty file (so a `.filez4eva.yml` in the working directory is ignored). Tests that need such state set it up in a temporary location. `test/test_environment.py` checks the isolation is in place.

## Libraries

The application uses the following external libraries:

- [WizLib](https://wizlib.steamwiz.io/) for CLI and configuration handling
- [Kwark](https://github.com/SteamWiz/Kwark) (its `kwark.ai` library layer) for transcribing files to Markdown and classifying them with Claude. Filez4Eva passes its own settings (model, API key) as arguments and never reads Kwark's configuration. Tests mock `kwark.ai.transcribe` and `kwark.ai.extract`, so no API calls are made.

Note that this application makes heavy use of WizLib and all code changes are expected to comply with, and take advantage of, the framework.
