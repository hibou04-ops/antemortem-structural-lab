# Original E7 publication verification after history rewriting

The `historical-e7-release` job checks the original `0.7.0a1` wheel and source
distribution. Their hashes, original source identity and annotated tag identity
remain publication provenance. The current Git tag has a separate, explicitly
pinned identity after the documentation history rewrite.

`scripts/verify-historical-e7-release.py` uses the unchanged publication verifier
from its pinned worktree. It first checks both current local and live remote tag
identities, then checks the original GitHub Release identity, exact asset set,
package hashes and checksum file. `docs/E7_PUBLICATION_HISTORY_MAP.json` records
the exact original and rewritten hashes and byte lengths of ten documents.

Only those document bytes are restored **in memory**, from the hash-verified
original source distribution. The adapter does not write them into Git or the
working tree. All 57 frozen product files, the original freeze manifest and
checker remain unchanged and are verified before the document mapping. The
unchanged verifier then checks every wheel and source-distribution member,
runtime inventory, package metadata, entry point and public-file scope. The live
PyPI version must still contain exactly the original two non-yanked files.

An unexpected ref, helper change, document change, product change, added runtime
file or package hash mismatch fails verification. The historical job keeps its
existing prerequisites and execution conditions. It performs no build, upload,
retagging or research evaluation, and does not convert original artifact hashes
into hashes of later source files.
