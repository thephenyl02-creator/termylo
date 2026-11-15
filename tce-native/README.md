# Termylo Context Engine (TCE) — native source

This is the **native TCE source tree**, not a separate DigUp application or
a runtime dependency on the original project's executable.

The engine, model integration, platform readers, search service, CLI,
evaluation suite, tests and desktop shell source were imported as a complete
source baseline, renamed to TCE, and kept in one Termylo repository.

**Build status:** source-level parity is verified; native executable parity
is not verified. This source tree must not yet replace the existing running
context engine. The Windows Swift toolchain and native vendor dependencies
are not ready in the current environment.

The Swift package produces `tce` / `tce.exe` and `TCEKit`, rather than
the former upstream product names. After native build, compare outputs
against the frozen baseline, wire Termylo's installer to `tce.exe`,
then remove the legacy executable only after all acceptance gates pass.

See ../docs/TCE_NATIVE_MIGRATION.md for the exact gates and limitations.

## Provenance and licensing

Derived from Abdur Rahim's MIT-licensed DigUp repository at tag
v0.7.0-beta.3, commit 0943225c2690c0631c01041e5dcb77c53e04395e.
The unmodified upstream MIT license remains in LICENSE. Other third-party
licenses remain in scripts/licenses. Provenance/attribution is legally
required, but DigUp is not intended to remain a separate installed runtime.
