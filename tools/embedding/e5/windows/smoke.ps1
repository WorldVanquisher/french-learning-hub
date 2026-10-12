# FLH-054: local smoke test against a running service. Sends two synthetic
# inputs (one search-query envelope, one Concept document); no learner data.
param([string]$BaseUrl = 'http://127.0.0.1:8765')
$ErrorActionPreference = 'Stop'
$ready = Invoke-RestMethod -Uri "$BaseUrl/readyz"
if (-not $ready.ready) { throw "not ready: $($ready.state)" }
$manifest = Invoke-RestMethod -Uri "$BaseUrl/manifest"
$id = $manifest.deployment_id
Write-Output "deployment_id: $id"
Write-Output "manifest_sha256: $($manifest.manifest_sha256)"
$inputs = @(
    '{"representation":"concept_search_query_v2","type":"query","text":"smoke test"}',
    '{"representation":"concept_embedding_text_v1","type":"concept","target":"smoke test","pedagogical_intent":"grammar","scope":"","identity_features":[]}'
)
$body = @{ model = $id; input = $inputs } | ConvertTo-Json -Compress
$resp = Invoke-RestMethod -Uri "$BaseUrl/v1/embeddings" -Method Post -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
foreach ($item in $resp.data) {
    $v = [double[]]$item.embedding
    $norm = [math]::Sqrt(($v | ForEach-Object { $_ * $_ } | Measure-Object -Sum).Sum)
    Write-Output ("index {0}: {1} dims, L2 norm {2:N6}" -f $item.index, $v.Length, $norm)
    if ($v.Length -ne 768 -or [math]::Abs($norm - 1) -gt 0.001) { throw "unexpected vector" }
}
$metrics = Invoke-RestMethod -Uri "$BaseUrl/metrics"
$metrics.counters | ConvertTo-Json -Compress
$metrics.gpu | ConvertTo-Json -Compress
