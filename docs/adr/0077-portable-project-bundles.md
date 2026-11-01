# 0077. Portable project bundles: one file with the project and every file it uses

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A project file points at files on the disk it was made on: the sounds on the timeline ([0034](0034-audio-track.md))
and the pictures of image and SVG layers ([0027](0027-svg-layers-and-media-files.md)), by absolute path. Copying the
project file to another computer leaves placeholders and silence. Snapshots ([0068](0068-named-project-snapshots.md))
copy the project, not its files. Sending a project meant collecting its files by hand and re-picking each one.

## Decision

- **A bundle is one zip file, `.msbundle`** (a distinct extension, so it is not mistaken for any zip; Open Bundle
  also accepts `.zip`). It holds `manifest.json`, `project.json`, `assets/<name>` for each file once however many
  layers use it, and, when asked, `snapshots/<id>.json` and `<id>.meta.json`.
- **One module knows where the files are.** `core/exchange/bundle.external_references(project)` lists every
  file a project uses (a media layer's `params.path`, a sound's `path`) with the layer or sound that uses it.
  Code layers, Python objects and helpers are inside the project file already, and fonts are named, not files.
- **The manifest** has the format (`"manim-studio-bundle"`, version 1), the app version, the project's name,
  the project's sha256 and, for each file, its path in the bundle, sha256, size, original path, the layers and
  sounds that use it and `missing`. In `project.json` (and the snapshots) every carried file's path becomes
  `assets/<name>`.
- **A missing file does not stop the bundle**: it is marked missing in the manifest, the project keeps its
  original path (a placeholder where it is opened, as today), and File > Export Bundle... lists it before
  asking where to write and warns after.
- **Opening unpacks into a new folder** beside the bundle, named after the project (`talk`, then `talk (2)`...):
  nothing that exists is ever written over. The paths are rewritten to the unpacked files, absolute like every
  other path, and the project opens as if from File > Open.
- **A bundle is untrusted data.** Before anything is written: every entry must be a relative path with forward
  slashes and no `..`, `.`, drive or empty part (zip-slip), the manifest must list every entry and every entry
  it lists must be there, assets live only in `assets/` and snapshots only in `snapshots/`, a newer format is
  refused, and the whole unpacks to at most 4 GB (sizes are checked again while reading, as a header can lie).
  Every file's sha256, the project's included, must match the manifest. On any failure the new folder is
  removed and nothing else was touched.
- **Trust does not travel** ([0019](0019-code-layers.md)). Trust is kept on this computer by the hash of the
  code; a bundle carries no trust, opening one never reads or writes the trust store, and anything else in
  the zip is refused. The code inside is asked about like the code of any file opened.

## Consequences

- A bundle is self-contained for what the editor draws and plays. A path written inside a code layer's own
  Python (`SVGMobject("C:/...")`) is the code's business and is not found or carried.
- The same file used by two layers is carried once; two different files with the same name get `name-2.ext`.
- Code whose exact text the user already trusted on this computer runs without asking, as it would from any
  file: trust is about the code, not where it came from.
- `project.json` inside the zip has relative `assets/` paths; it is meant to be opened with Open Bundle, not
  unzipped by hand.

## Alternatives considered

- **Project-relative paths in every project** - would make a folder portable, but changes what every existing
  file means; a bundle leaves the format as it is.
- **Unpack over an existing folder** - could overwrite the user's files; a fresh folder is always safe.
- **Carry trust in the manifest** - anyone could write it; trust must be the user's decision on their machine.

## Evidence

- Tests: `tests/core/exchange/test_bundle.py`, `tests/ui/exchange/test_bundle_ui.py`.
