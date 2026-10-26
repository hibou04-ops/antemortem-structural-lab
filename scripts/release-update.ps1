param(
    [Parameter(Mandatory = $true)][string]$ExpectedHead,
    [string]$Repository = 'hibou04-ops/antemortem-structural-lab',
    [string]$Python = 'python',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $($Arguments[0])" }
    return $result
}
if ($Repository -ne 'hibou04-ops/antemortem-structural-lab') { throw 'Unexpected repository' }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repoRoot
try {
    $remote = (Invoke-Checked git @('remote', 'get-url', 'origin')).Trim()
    if ($remote -notin @("https://github.com/$Repository.git", "git@github.com:$Repository.git")) { throw 'Remote mismatch' }
    Invoke-Checked git @('fetch', 'origin', '--tags', '--prune') | Out-Null
    $head = (Invoke-Checked git @('rev-parse', 'HEAD')).Trim()
    $branch = (Invoke-Checked git @('branch', '--show-current')).Trim()
    $remoteHead = (Invoke-Checked git @('rev-parse', 'origin/main')).Trim()
    if ($head -ne $ExpectedHead -or $head -ne $remoteHead -or $branch -ne 'main') { throw 'Expected clean final main required' }
    if (Invoke-Checked git @('status', '--porcelain')) { throw 'Working tree must be clean' }
    $version = (Invoke-Checked $Python @('-c', 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')).Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+(a|b|rc)\d+$') { throw 'This script publishes experimental prereleases only' }
    $tag = "v$version"
    if (Invoke-Checked git @('tag', '--list', $tag)) { throw 'Tag already exists; never overwrite' }
    $releases = (Invoke-Checked gh @('release', 'list', '--repo', $Repository, '--limit', '100', '--json', 'tagName')) | ConvertFrom-Json
    if ($releases.tagName -contains $tag) { throw 'Release already exists; never overwrite' }
    $runs = (Invoke-Checked gh @('run', 'list', '--repo', $Repository, '--commit', $head, '--branch', 'main', '--json', 'status,conclusion,workflowName,event')) | ConvertFrom-Json
    $checks = @($runs | Where-Object { $_.workflowName -eq 'Python tests' -and $_.event -eq 'push' })
    if ($checks.Count -eq 0 -or @($checks | Where-Object { $_.status -ne 'completed' -or $_.conclusion -ne 'success' }).Count -ne 0) { throw 'Final main CI is missing or not successful' }
    Invoke-Checked $Python @('-m', 'pytest', '-q')
    # Do not delete mixed artifacts. Stop and require an explicitly clean build directory.
    if (Test-Path dist) {
        $unexpected = @(Get-ChildItem dist -File | Where-Object { $_.Name -notlike "antemortem_structural_lab-$version*" })
        if ($unexpected.Count) { throw 'dist contains artifacts from another version' }
    }
    Invoke-Checked $Python @('-m', 'build')
    $assets = @(Get-ChildItem dist -File | Where-Object { $_.Name -like '*.whl' -or $_.Name -like '*.tar.gz' })
    if ($assets.Count -ne 2) { throw 'Expected one wheel and one sdist' }
    Invoke-Checked $Python (@('-m', 'twine', 'check') + @($assets.FullName))
    Invoke-Checked $Python @('scripts/check-public-scope.py')
    Invoke-Checked $Python @('scripts/check-wheel.py')
    $notes = "docs/releases/$tag.md"
    if (-not (Test-Path -LiteralPath $notes)) { throw 'Matching release notes missing' }
    $receipt = [ordered]@{schema='tomolab-release-update-v1'; repository=$Repository; head=$head; tag=$tag; dry_run=[bool]$DryRun; assets=@($assets | ForEach-Object { @{name=$_.Name; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()} }); published=$false}
    New-Item -ItemType Directory -Force -Path results | Out-Null
    $finalHead = (Invoke-Checked git @('rev-parse', 'HEAD')).Trim()
    $finalRemote = (Invoke-Checked git @('ls-remote', 'origin', 'refs/heads/main')).Split()[0]
    if ($finalHead -ne $head -or $finalRemote -ne $head -or (Invoke-Checked git @('status', '--porcelain'))) { throw 'Source or remote changed during validation' }
    if (Invoke-Checked git @('ls-remote', '--tags', 'origin', "refs/tags/$tag")) { throw 'Remote tag appeared during validation' }
    if (-not $DryRun) {
        Invoke-Checked git @('tag', '-a', $tag, $head, '-m', "Antemortem Structural Lab $tag")
        Invoke-Checked git @('push', 'origin', $tag)
        Invoke-Checked gh (@('release', 'create', $tag) + @($assets.FullName) + @('--repo', $Repository, '--verify-tag', '--prerelease', '--latest=false', '--title', "$tag (experimental)", '--notes-file', $notes, '--draft'))
        $draft = (Invoke-Checked gh @('release', 'view', $tag, '--repo', $Repository, '--json', 'isDraft,isPrerelease,tagName,assets')) | ConvertFrom-Json
        if (-not $draft.isDraft -or -not $draft.isPrerelease -or $draft.tagName -ne $tag -or $draft.assets.Count -ne 2) { throw 'Draft validation failed; left unpublished' }
        foreach ($asset in $assets) {
            $remoteAsset = @($draft.assets | Where-Object { $_.name -eq $asset.Name })
            $hash = (Get-FileHash -LiteralPath $asset.FullName -Algorithm SHA256).Hash.ToLower()
            if ($remoteAsset.Count -ne 1 -or $remoteAsset[0].size -ne $asset.Length -or $remoteAsset[0].digest -ne "sha256:$hash") { throw 'Draft asset size/digest mismatch; left unpublished' }
        }
        Invoke-Checked gh @('release', 'edit', $tag, '--repo', $Repository, '--draft=false', '--prerelease', '--latest=false')
        $receipt.published = $true
        $receipt.readback = (Invoke-Checked gh @('release', 'view', $tag, '--repo', $Repository, '--json', 'url,isDraft,isPrerelease,tagName,assets')) | ConvertFrom-Json
        if ($receipt.readback.isDraft) { throw 'Release remains draft' }
    }
    $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath 'results/release-receipt.json' -Encoding utf8
    $receipt | ConvertTo-Json -Depth 4
} finally {
    Pop-Location
}
