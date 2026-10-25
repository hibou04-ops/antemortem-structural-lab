# Publish the prebuilt, local three-tag history after reviewing the public tree.
# Run from a clone of the accompanying Git bundle, not from private Drive archives.
$ErrorActionPreference = 'Stop'
$repo = 'hibou04-ops/antemortem-structural-lab'
$tags = @('v0.1.0','v0.1.1','v0.2.0')
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required: https://git-scm.com/' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI is required: https://cli.github.com/' }
gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Authenticate with gh auth login before publishing' }
$branch = git branch --show-current
if ($branch -ne 'main') { throw "Expected local main branch, got $branch" }
$dirty = git status --porcelain
if ($dirty) { throw 'Working tree is not clean. Inspect changes before publishing.' }
foreach ($tag in $tags) { git rev-parse --verify "refs/tags/$tag" | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Missing $tag" } }
Write-Host 'Review the tree, history, and staged release notes before public publishing:'
git log --oneline --decorate -7
git ls-files
Write-Host ''
Write-Host "This action publishes code and GitHub Releases publicly to $repo."
$confirmation = Read-Host 'Type PUBLISH to confirm'
if ($confirmation -cne 'PUBLISH') { throw 'Cancelled, no publishing performed.' }
gh repo view $repo --json name > $null 2>&1
if ($LASTEXITCODE -eq 0) { throw "$repo already exists. Manual inspection is required to prevent accidental overwrite." }
# A local Git bundle clone has origin pointing at the local .bundle file.
# Remove only that known temporary origin; never rewrite an unexpected remote.
$existingOrigin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    if ($existingOrigin -like '*.bundle') {
        git remote remove origin
        if ($LASTEXITCODE -ne 0) { throw 'Cannot remove local bundle origin' }
    } else {
        throw "Unexpected existing origin: $existingOrigin. Review the remote manually before publishing."
    }
}
gh repo create $repo --public --source . --remote origin --push --description 'Experimental MRI-CAST feedback and claim-to-witness research tools'
if ($LASTEXITCODE -ne 0) { throw 'Repository creation or initial push failed' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'Could not push main' }
git push origin $tags
if ($LASTEXITCODE -ne 0) { throw 'Could not push tags' }
foreach ($tag in $tags) {
    gh release view $tag --repo $repo > $null 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host "Release $tag already exists; preserving it."; continue }
    $version = $tag.TrimStart('v')
    $wheelDir = Join-Path (Split-Path -Parent (Get-Location)) 'release-assets'
    $wheel = Join-Path $wheelDir "antemortem_structural_lab-$version-py3-none-any.whl"
    $releaseArgs = @('release', 'create', $tag, '--repo', $repo, '--verify-tag', '--prerelease', '--title', "$tag (experimental)", '--notes-file', "docs/releases/$tag.md")
    if (Test-Path $wheel) { $releaseArgs += $wheel }
    & gh @releaseArgs
    if ($LASTEXITCODE -ne 0) { throw "Could not create release $tag" }
}
gh repo view $repo --json url,isPrivate,defaultBranchRef
gh release list --repo $repo
Write-Host 'PUBLISHED — inspect GitHub Actions before declaring CI success.'
