# CHANGELOG

<!-- version list -->

## v5.3.0 (2026-10-17)

### Features

- Upgrade wizlib to 4.1.0 and document op:// config secrets
  ([#50](https://github.com/SteamWiz/Filez4Eva/pull/50),
  [`7c1a966`](https://github.com/SteamWiz/Filez4Eva/commit/7c1a966ab76bbe576c5ab33cec5b44ea88a04645))

### Breaking Changes

- Config values using $(...) command substitution are no longer executed and are used as literal
  text. Replace `$(op read op://vault/item/field)` with `op://vault/item/field`. The `op` CLI must
  be installed and signed in; a failure is reported as a config error. FILEZ4EVA_ANTHROPIC_KEY
  values are used as given and never resolved.


## v5.2.0 (2026-10-15)

### Bug Fixes

- **stow-file**: Order fields by first placeholder including {date.year}; ignore unknown stdin data
  keys
  ([`d7d3e91`](https://github.com/SteamWiz/Filez4Eva/commit/d7d3e917c4a7b89b7ddcb36df567c723ea4a0fb5))

### Features

- Cabinet-specific fields from the pattern, with guidance and learned values
  ([#43](https://github.com/SteamWiz/Filez4Eva/pull/43),
  [`4e507b7`](https://github.com/SteamWiz/Filez4Eva/commit/4e507b782f13b3cf645ad5f0dbf022957acd4966))

### Breaking Changes

- The fixed account and part fields are removed. The default pattern is now '{date}-{title}'; {year}
  is now {date.year} and {ext} is no longer used (the extension is always appended). stow-file
  --account/-a and --part/-p are replaced by --field/-f NAME=VALUE. In classify output and stow-file
  stdin, fields (including date) are under `data:`. Tab completion no longer scans existing folders.


## v5.1.1 (2026-10-14)

### Bug Fixes

- **classify**: Drop per-cabinet date guidance and keep only the null-date fix
  ([#45](https://github.com/SteamWiz/Filez4Eva/pull/45),
  [`22f26c8`](https://github.com/SteamWiz/Filez4Eva/commit/22f26c8a62790e6aed48c2831bbaf87fcc700d34))

- **classify**: Treat a missing or invalid date as null instead of failing
  ([#45](https://github.com/SteamWiz/Filez4Eva/pull/45),
  [`9b5e00f`](https://github.com/SteamWiz/Filez4Eva/commit/9b5e00f75d55205bbccaaf2ddeed1f0c5217dbf7))


## v5.1.0 (2026-10-11)

### Bug Fixes

- Reject non-mapping top-level transcripts config
  ([#15](https://github.com/SteamWiz/Filez4Eva/pull/15),
  [`d8ccb45`](https://github.com/SteamWiz/Filez4Eva/commit/d8ccb4577c3fb639a1f203233f339746bf6c4986))

- **stow-file**: Treat empty top-level transcripts block as unset and reject falsy locations
  ([`af32746`](https://github.com/SteamWiz/Filez4Eva/commit/af32746ce1e762b80bda19a2a52649cd06be9280))

### Build System

- **deps**: Bump the actions group across 1 directory with 4 updates
  ([`8ef610e`](https://github.com/SteamWiz/Filez4Eva/commit/8ef610e607f43a61bf16ddc44bc26c96497419fa))

### Documentation

- Refer to the AI model generically instead of Claude in PACKAGE.md
  ([`6afc30b`](https://github.com/SteamWiz/Filez4Eva/commit/6afc30bc0db440ebafe4dd1ad5e1a278a1871d3f))

### Features

- Add classify command proposing date, account, part and doctype
  ([#16](https://github.com/SteamWiz/Filez4Eva/pull/16),
  [`1895c6e`](https://github.com/SteamWiz/Filez4Eva/commit/1895c6e16009c81771e17f89ebc85ca72f977987))

- Add process command to transcribe, classify, confirm and stow a file
  ([#17](https://github.com/SteamWiz/Filez4Eva/pull/17),
  [`01dd0ea`](https://github.com/SteamWiz/Filez4Eva/commit/01dd0eabddf179691013ccf4ca330895dc0a4872))

- Add transcribe command writing a Markdown transcript next to the file
  ([#12](https://github.com/SteamWiz/Filez4Eva/pull/12),
  [`327377c`](https://github.com/SteamWiz/Filez4Eva/commit/327377ca27cd6c076632d8c532418738af811ffb))

- Configurable transcript location for stow-file
  ([#15](https://github.com/SteamWiz/Filez4Eva/pull/15),
  [`9f404bc`](https://github.com/SteamWiz/Filez4Eva/commit/9f404bc7f7bbc793b6a6892fbf0d7eb189081092))

- Move transcript with the file in stow-file ([#14](https://github.com/SteamWiz/Filez4Eva/pull/14),
  [`6051899`](https://github.com/SteamWiz/Filez4Eva/commit/6051899381738989879b3102dbcf7f7ec3e1e135))

- Skip transcript files in scan-dir and delete them with their file
  ([#13](https://github.com/SteamWiz/Filez4Eva/pull/13),
  [`d1103d4`](https://github.com/SteamWiz/Filez4Eva/commit/d1103d44c0207c0a1f09f606a4826b3c06276446))

- **scan-dir**: Pre-fill stow prompts from AI transcription and classification
  ([#18](https://github.com/SteamWiz/Filez4Eva/pull/18),
  [`3ecc045`](https://github.com/SteamWiz/Filez4Eva/commit/3ecc0450fe4ffcd93c03996321e2b728576cd258))

### Refactoring

- Rename transcript locations to adjacent/parallel
  ([#15](https://github.com/SteamWiz/Filez4Eva/pull/15),
  [`57abf6d`](https://github.com/SteamWiz/Filez4Eva/commit/57abf6d3f83fbac50eb93964df723ca80ad35141))


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
