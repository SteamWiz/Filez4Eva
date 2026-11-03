# CHANGELOG

<!-- version list -->

## v6.0.0 (2026-11-03)

### Bug Fixes

- **ingest**: Give each document its own stamp so X.yml/X.md can't land on another document
  ([#62](https://github.com/SteamWiz/Filez4Eva/pull/62),
  [`7d5661e`](https://github.com/SteamWiz/Filez4Eva/commit/7d5661e6eec9446d90472ea8ebb34963a401494f))

- **ingest**: Lock the intake around stamp check-and-claim so concurrent runs never share a stamp
  ([#62](https://github.com/SteamWiz/Filez4Eva/pull/62),
  [`7d5661e`](https://github.com/SteamWiz/Filez4Eva/commit/7d5661e6eec9446d90472ea8ebb34963a401494f))

- **ingest**: Only treat X/X.yml pairs as ingested inside the intake
  ([#62](https://github.com/SteamWiz/Filez4Eva/pull/62),
  [`7d5661e`](https://github.com/SteamWiz/Filez4Eva/commit/7d5661e6eec9446d90472ea8ebb34963a401494f))

- **review**: Delete only the document's own X.md and X.yml
  ([#66](https://github.com/SteamWiz/Filez4Eva/pull/66),
  [`a978d9b`](https://github.com/SteamWiz/Filez4Eva/commit/a978d9b6b1ab80ad8c898f5f4c6d934c9f16d084))

- **stage**: Complete given data on a classified document records the review without the menu
  ([#83](https://github.com/SteamWiz/Filez4Eva/pull/83),
  [`975e23a`](https://github.com/SteamWiz/Filez4Eva/commit/975e23afec5ab9675169c2ec9a469e748883bea5))

- **stage**: Report paths as given and run PR Checks on epic branches (#65)
  ([#67](https://github.com/SteamWiz/Filez4Eva/pull/67),
  [`a7b9848`](https://github.com/SteamWiz/Filez4Eva/commit/a7b984819b2baba51c6c1a79c9f68fb1947baee1))

- **stow**: Save input record as results.review only after the file is stowed
  ([#69](https://github.com/SteamWiz/Filez4Eva/pull/69),
  [`0db1ae9`](https://github.com/SteamWiz/Filez4Eva/commit/0db1ae9d915b0cb4b3c3954ca4314b27233dd1f6))

- **transcribe**: Resolve directory paths fully so links into intake subdirectories are refused
  ([#63](https://github.com/SteamWiz/Filez4Eva/pull/63),
  [`a11acb8`](https://github.com/SteamWiz/Filez4Eva/commit/a11acb857ae178c66a6b201a9f4071cbd67034ea))

### Features

- Add ingest command that moves files into the intake with an X.yml sidecar
  ([#62](https://github.com/SteamWiz/Filez4Eva/pull/62),
  [`7d5661e`](https://github.com/SteamWiz/Filez4Eva/commit/7d5661e6eec9446d90472ea8ebb34963a401494f))

- Add ingest command with normalized intake names and X.yml sidecar
  ([#62](https://github.com/SteamWiz/Filez4Eva/pull/62),
  [`7d5661e`](https://github.com/SteamWiz/Filez4Eva/commit/7d5661e6eec9446d90472ea8ebb34963a401494f))

- Remove stow-file, scan-dir and process; document the five stage commands (#60)
  ([#70](https://github.com/SteamWiz/Filez4Eva/pull/70),
  [`7086ad4`](https://github.com/SteamWiz/Filez4Eva/commit/7086ad4f05cd67d5cef49821d7826e045749844d))

- **classify**: Classify a file, a directory or the intake and save results.classify (#56)
  ([#64](https://github.com/SteamWiz/Filez4Eva/pull/64),
  [`9421080`](https://github.com/SteamWiz/Filez4Eva/commit/9421080d7c606c5471cd8c0cbf730224705199d0))

- **config**: Require absolute paths for target, intake and transcripts root (#79)
  ([#89](https://github.com/SteamWiz/Filez4Eva/pull/89),
  [`60268a8`](https://github.com/SteamWiz/Filez4Eva/commit/60268a8c0489a28326bdc168c5de1c3590313cc9))

- **review**: (c)onfirm saves the proposed record as is, (u)pdate edits it, (r)edo changes the
  cabinet and classifies again (#73) ([#82](https://github.com/SteamWiz/Filez4Eva/pull/82),
  [`3978570`](https://github.com/SteamWiz/Filez4Eva/commit/3978570cd6de13fa65b8debcc4fa4f82e9406a8d))

- **review**: Record learned values when the review is saved, not at stow (#75)
  ([#84](https://github.com/SteamWiz/Filez4Eva/pull/84),
  [`05f493a`](https://github.com/SteamWiz/Filez4Eva/commit/05f493a608a2401ffc992cf17a297fce724cf0c2))

- **review**: Review a file, a directory or the intake and save results.review
  ([#66](https://github.com/SteamWiz/Filez4Eva/pull/66),
  [`a978d9b`](https://github.com/SteamWiz/Filez4Eva/commit/a978d9b6b1ab80ad8c898f5f4c6d934c9f16d084))

- **review**: Review a file, a directory or the intake and save results.review (#57)
  ([#66](https://github.com/SteamWiz/Filez4Eva/pull/66),
  [`a978d9b`](https://github.com/SteamWiz/Filez4Eva/commit/a978d9b6b1ab80ad8c898f5f4c6d934c9f16d084))

- **stage**: Choose the cabinet before classify with --cabinet or a per-file prompt; the model never
  picks it (#72) ([#81](https://github.com/SteamWiz/Filez4Eva/pull/81),
  [`d7ef7b4`](https://github.com/SteamWiz/Filez4Eva/commit/d7ef7b4f5a7375643b3f6b9e7a928ef8eb5c5f31))

- **stage**: Given data for any run: --cabinet/--date/--field and stdin apply to every document;
  classify fills only the rest ([#83](https://github.com/SteamWiz/Filez4Eva/pull/83),
  [`975e23a`](https://github.com/SteamWiz/Filez4Eva/commit/975e23afec5ab9675169c2ec9a469e748883bea5))

- **stage**: Given data for any run; classify fills only the rest (#74)
  ([#83](https://github.com/SteamWiz/Filez4Eva/pull/83),
  [`975e23a`](https://github.com/SteamWiz/Filez4Eva/commit/975e23afec5ab9675169c2ec9a469e748883bea5))

- **stage**: Path means new files only, no path means the intake, --ingested; transcribe in a batch,
  then one file at a time (#71) ([#80](https://github.com/SteamWiz/Filez4Eva/pull/80),
  [`f8dbcd9`](https://github.com/SteamWiz/Filez4Eva/commit/f8dbcd9a36070eca8cabcd73805cce4ef9171502))

- **stage**: Progress output on stderr: stage and file for every step, stowed path, AI spinner (#44)
  ([#85](https://github.com/SteamWiz/Filez4Eva/pull/85),
  [`ec04e59`](https://github.com/SteamWiz/Filez4Eva/commit/ec04e598c7f68d5936c10745b04e3465a2a610b1))

- **stage**: Record the original file's created/modified time at ingest and show the file date to
  the classifier (#77) ([#87](https://github.com/SteamWiz/Filez4Eva/pull/87),
  [`f0ec02e`](https://github.com/SteamWiz/Filez4Eva/commit/f0ec02eb41c54dbfd7dbf0e040f216e52c170e24))

- **stage**: Text documents skip transcription and stand in for their transcript; classifier input
  capped at 100,000 characters (#76) ([#86](https://github.com/SteamWiz/Filez4Eva/pull/86),
  [`2d65948`](https://github.com/SteamWiz/Filez4Eva/commit/2d65948be96a20da1274a4ee02002a4591195962))

- **stow**: Stow a file, a directory or the intake, reviewing first if needed, and archive X.yml
  (#58) ([#68](https://github.com/SteamWiz/Filez4Eva/pull/68),
  [`1d0082e`](https://github.com/SteamWiz/Filez4Eva/commit/1d0082ebec7be6270d2a426d914681b5502f37a6))

- **stow**: Take a record from flags or stdin and skip classify/review (#59)
  ([#69](https://github.com/SteamWiz/Filez4Eva/pull/69),
  [`0db1ae9`](https://github.com/SteamWiz/Filez4Eva/commit/0db1ae9d915b0cb4b3c3954ca4314b27233dd1f6))

- **stow**: Take a record from flags or stdin for a single file and skip classify and review
  ([#69](https://github.com/SteamWiz/Filez4Eva/pull/69),
  [`0db1ae9`](https://github.com/SteamWiz/Filez4Eva/commit/0db1ae9d915b0cb4b3c3954ca4314b27233dd1f6))

- **transcribe**: Transcribe a file, a directory or the intake on the sidecar model
  ([#63](https://github.com/SteamWiz/Filez4Eva/pull/63),
  [`a11acb8`](https://github.com/SteamWiz/Filez4Eva/commit/a11acb857ae178c66a6b201a9f4071cbd67034ea))

- **transcribe**: Write the transcript header as a fenced YAML block instead of front matter (#78)
  ([#88](https://github.com/SteamWiz/Filez4Eva/pull/88),
  [`d9ca804`](https://github.com/SteamWiz/Filez4Eva/commit/d9ca804492de41dcd87d2a5ed5cd8c992ff60b41))

### Breaking Changes

- **config**: Relative directory paths in the configuration, previously taken from the working
  directory, are now rejected.


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
