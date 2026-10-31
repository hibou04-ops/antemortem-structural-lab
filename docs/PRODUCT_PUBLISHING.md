# Product publication / 제품 발행

The product release is authorized separately by `PRODUCT_RELEASE_AUTHORIZATION.json`. This does not qualify research guidance, authorize final Target reuse, or change frozen `allow_release=false` records. The user explicitly authorized this experimental product release on 2026-11-01.

1. Merge a reviewed product PR into main through normal repository policy. Wait for the exact merge commit's complete `Python tests` run, including `product-installation`.
2. Dispatch the existing **publish-pypi.yml** workflow on main with `version` and the exact `release_sha`. The source must equal both the dispatch commit and current main. All required product CI jobs must have succeeded on that SHA.
3. The workflow's first job creates or verifies **an annotated tag** `v{version}` after checking CI. Existing tags are never moved. This keeps tag creation within the same normal publication authority when the operator uses the workflow rather than a local authenticated Git client.
4. Build the final wheel and sdist **once** from that commit. Preflight CI builds are separate. The final pair is metadata/scope checked and independently installed before the product gate can authorize publication.
5. Prepare a GitHub Draft Release containing the same pair, checksums, and a release manifest. Artifact handoffs recheck source identity, approval, installation receipts, inventory and hashes.
6. The existing project-scoped Trusted Publisher uses the unchanged workflow filename and `pypi` environment. Only its publish job has `id-token: write`. The upload directory contains only missing, hash-checked wheel/sdist files. Conflicts fail; `skip-existing` is false.
7. Download the exact public PyPI wheel and sdist, compare their bytes and English long description, and install each outside the checkout. Only after these pass does the workflow make the GitHub prerelease public and independently download its public assets for hash equality.

Ordinary PR, main and tag tests do not publish. The previous automatic E8 prerelease job was removed; its research checker and authorization remain historical records. Historical E7 publication scripts and fixed `0.7.0a1` files are checked at commit `3739e7dee2a7064d1c73f2c29dac30dc7c2eefe1`, rather than treating the product workflow as the old E7 publisher.

## Partial states

Read the exact workflow run and retained `product-distributions`, `product-validation`, `product-checksums` and publication receipts. Do not rebuild an already published version, move a tag, delete/yank a file, or use a hash conflict as a reason to skip it. A failed publish job can be resumed through the normal failed-job path using the retained approved artifacts: the upload-directory check compares every existing registry file and stages only missing approved files. If PyPI already succeeded, rerun only the failed readback/finalization job; do not repeat the upload. Authentication or repository-policy failures require the actual missing authorization, never an administrator bypass.

The final public verification receipt records version, source commit, tag, public URLs and matching hashes. A successful upload alone is not completion.
