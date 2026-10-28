# Local-only UTF-8 smoke test for experimental ClickUp Brain gateway.
# Works in Windows PowerShell 5.1 and PowerShell 7+.
# Start local_gateway.py in a different terminal before running.
[CmdletBinding()]
param(
    [string]$Prompt = 'Trả lời đúng một từ: OK',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787,
    [string]$KeyFile = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($KeyFile)) {
    $KeyFile = Join-Path (Split-Path -Parent $PSScriptRoot) '.local\gateway.key'
}
if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) {
    throw 'Local API key file not found. Start with docs/15_LOCAL_HTTP_GATEWAY.md.'
}
$apiKey = (Get-Content -LiteralPath $KeyFile -Raw).Trim()
if ($apiKey.Length -lt 24) {
    throw 'Local API key must contain at least 24 characters.'
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw 'Prompt cannot be empty.'
}

$payload = @{
    model = 'clickup-ui-current'
    messages = @(@{ role = 'user'; content = $Prompt })
    stream = $false
} | ConvertTo-Json -Depth 5 -Compress

# Windows PowerShell 5.1 may encode string -Body with a non-UTF-8 code page.
# Always send UTF-8 BYTES, not a string, for Vietnamese/Unicode messages.
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($payload)
$headers = @{ Authorization = ('Bearer ' + $apiKey) }
$uri = ('http://127.0.0.1:{0}/v1/chat/completions' -f $Port)

$reply = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $utf8Body -ErrorAction Stop

if ($null -eq $reply.choices -or $reply.choices.Count -lt 1) {
    throw 'Gateway did not return a Chat Completions choice.'
}

# Print ONLY the answer, not request JSON or private authentication.
$reply.choices[0].message.content
