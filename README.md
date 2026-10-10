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

## Libraries

The application uses the following external libraries:

- [WizLib](https://wizlib.steamwiz.io/) for CLI and configuration handling
- [Kwark](https://github.com/SteamWiz/Kwark) (its `kwark.ai` library layer) for transcribing files to Markdown with Claude. Filez4Eva passes its own settings (model, API key) as arguments and never reads Kwark's configuration. Tests mock `kwark.ai.transcribe`, so no API calls are made.

Note that this application makes heavy use of WizLib and all code changes are expected to comply with, and take advantage of, the framework.
