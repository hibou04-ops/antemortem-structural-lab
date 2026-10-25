# Public Git history provenance

The v0.1.0, v0.1.1, and v0.2.0 experiments were initially developed and archived outside Git. Their code snapshots were validated, reviewed for public release, and imported sequentially into this repository later.

The Git commits are **reconstructed import events**, not contemporaneous evidence of when each idea was first written. This is intentionally visible in the commit messages and annotated tag messages. Original generated result JSONs and `build/lib/` artifacts were excluded: some contained absolute paths to temporary development machines or duplicated source files. The public source and regression fixtures are available.

Research reports describing unrelated private work, secrets and real API credentials were not imported. No published version implies production-grade reliability, universally sound AI verification, or an advantage over established tools.

## Unpublished v0.2.0 tag finalization

Before publication, an authenticated GitHub lookup confirmed that the intended repository did not exist. The original release kit is preserved unchanged. Its v0.2.0 annotated tag object was `d1aa9ecacaf6a38ff2cd95b5ade997e70e6c2596`, pointing to commit `375e010124706a498d026045624dc10adf0a2d23`.

The local v0.2.0 tag was finalized on the subsequent public release commit so that its source archive, bilingual README, package description and rebuilt distribution agree. All original commits remain ancestors of the public main branch. The v0.1.0 and v0.1.1 tag objects are unchanged, including the explicit v0.1.1 package metadata repair. Historical READMEs in those two tags retain their archived wording; the release notes describe their historical scope.

The finalization adds documentation, explicit UTF-8 reading in one Windows-sensitive test, and distribution metadata. A wheel installation check also exposed missing bundled examples; the wheel now includes them, and the CLI locates the installed copies. Git attributes fix text line endings for byte-level source/distribution checks. The probing and claim algorithms are unchanged. These fixes do not backdate commits or claim a new experimental result. The import bundle, original tag hashes and rebuilt artifact checksums are retained in the release audit.
