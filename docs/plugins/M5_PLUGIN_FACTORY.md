# M5 offline plugin factory

## Delivered boundary

This packet builds and verifies one local, skills-only Agent Plugins 1.0
reference package. The package has the required root `plugin.json`, one
immediate child skill, and a valid empty `mcp.json`. It contains no executable
component. Existing descriptive presets under `plugins/` remain unchanged.

The validator is deliberately narrower than a general Agent Plugins client. It
supports the inert reference profile, reports unknown manifest fields, checks
the 1.0.0 schema identifiers and name rules, validates simple skill
frontmatter, and accepts only an empty MCP server set. It must not be described
as complete client conformance.

All work is offline. The factory rejects symlinks, special files, escaping or
nonportable paths, case-folded collisions, duplicate JSON keys, and bounded
file/count overflows. It never fetches a schema, opens an archive, starts a
process from the package, imports package code, connects to MCP, or contacts a
cloud service.

## Generated evidence

`python -m plugin_factory build SOURCE DESTINATION` creates a disabled release
directory containing:

- `plugin/`: a copied, still-inert Agent Plugins directory;
- `evidence/sbom.cdx.json`: deterministic CycloneDX 1.7 file inventory;
- `evidence/provenance.intoto.json`: unsigned in-toto Statement v1 using the
  SLSA provenance v1 predicate;
- `bundle.json`: plugin identity, canonical tree digest, inventory, and
  evidence digests;
- `SHA256SUMS`: every other release file, sorted by portable relative path.

The SHA-256 of `SHA256SUMS` is the release digest and is required out of band
for verification. The evidence proves repeatable content integrity only. It is
not signed publisher identity, a SLSA level, installation safety, or production
readiness.

## Verification

The Python verifier performs both byte verification and semantic revalidation:

```sh
python -m plugin_factory verify RELEASE_DIR sha256:EXPECTED_RELEASE_DIGEST
```

Trusted convenience verifiers perform byte-only verification and never source
or execute package content:

```sh
sh plugin_factory/verifiers/verify-plugin.sh RELEASE_DIR sha256:EXPECTED_RELEASE_DIGEST
pwsh -File plugin_factory/verifiers/Verify-Plugin.ps1 RELEASE_DIR sha256:EXPECTED_RELEASE_DIGEST
```

A successful result is `verified_inert` with activation `disabled`. No files
are copied into a client plugin directory and no external installer is called.

Run the focused suite:

```sh
python -m unittest -v tests.plugin_factory.test_plugin_factory
```
