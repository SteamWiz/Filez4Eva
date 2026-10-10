# CHANGELOG

<!-- version list -->

## v5.0.0 (2026-10-10)

### Bug Fixes

- Enter at delete confirmation no longer deletes the file
  ([#1](https://github.com/SteamWiz/Filez4Eva/pull/1),
  [`0e8955c`](https://github.com/SteamWiz/Filez4Eva/commit/0e8955cb64c4887da2f9d92b980c338af0ab8640))

- Validate stow-file account and part and read stdin values as plain strings
  ([#9](https://github.com/SteamWiz/Filez4Eva/pull/9),
  [`e628c5b`](https://github.com/SteamWiz/Filez4Eva/commit/e628c5b42faf005fea5a24e69a22345384c02bf5))

- **stow-file**: Re-prompt on invalid account/part instead of aborting
  ([`088e1d8`](https://github.com/SteamWiz/Filez4Eva/commit/088e1d82f912a11b77cbbe26a870890aa608c04c))

### Build System

- Require Python 3.14 ([#7](https://github.com/SteamWiz/Filez4Eva/pull/7),
  [`491ff4d`](https://github.com/SteamWiz/Filez4Eva/commit/491ff4d9b411e2b3fc44b825a601934890f84210))

### Continuous Integration

- Name the pull-request workflow 'PR Checks'
  ([`a9140ad`](https://github.com/SteamWiz/Filez4Eva/commit/a9140adc94a1a9b8c10b1373579eade73bf22a37))

- Reference steamwiz/actions@v1
  ([`efda58d`](https://github.com/SteamWiz/Filez4Eva/commit/efda58d8a7ef2eacbd3b1a199f8dab6af3b4b593))

- Split PR checks from release; read-only PR token, one run per PR
  ([`1b303ba`](https://github.com/SteamWiz/Filez4Eva/commit/1b303babb1e3451bf8fc3d3d197cb001ed14f06e))

### Features

- Configurable destination path pattern ([#10](https://github.com/SteamWiz/Filez4Eva/pull/10),
  [`2507508`](https://github.com/SteamWiz/Filez4Eva/commit/2507508c977eec6324be79229dca09571e7c3ff4))

- Multiple named destinations (cabinets) for stow-file
  ([#11](https://github.com/SteamWiz/Filez4Eva/pull/11),
  [`038d0fd`](https://github.com/SteamWiz/Filez4Eva/commit/038d0fdb562f2c39aaa481d890e95304833f453a))

- Rename stow-dir command to scan-dir ([#4](https://github.com/SteamWiz/Filez4Eva/pull/4),
  [`027a808`](https://github.com/SteamWiz/Filez4Eva/commit/027a808fffbcea285c75942b9b3cd5620986f21c))

- Stow-file accepts date, account and part as YAML on stdin
  ([#9](https://github.com/SteamWiz/Filez4Eva/pull/9),
  [`763709b`](https://github.com/SteamWiz/Filez4Eva/commit/763709bc426d09aaa697c0efedb6fb93564ec12d))

- Stow-file prints absolute destination path on stdout
  ([#8](https://github.com/SteamWiz/Filez4Eva/pull/8),
  [`c69f280`](https://github.com/SteamWiz/Filez4Eva/commit/c69f28085136de588e2d68127e3ac8d05f3b7f86))


## v4.0.0 (2026-10-02)

### Chores

- MIT license, copyright 2026 Francis Potter
  ([`0278990`](https://github.com/SteamWiz/Filez4Eva/commit/0278990f6201ad21426ea44796fd6e2710776447))


## v3.0.13 (2026-10-01)

- Initial Release
