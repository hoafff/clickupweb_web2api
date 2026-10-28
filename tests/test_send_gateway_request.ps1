# Windows PowerShell 5.1 regression smoke test for UTF-8 gateway client.
# Synthetic data only; Invoke-RestMethod is mocked, so NO HTTP request is sent.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$global:GatewayMockCalls = 0
$global:GatewayMockExpectedPrompt = 'Xin ch' + [char]0x00E0 + 'o'  # "Xin chao" with a-grave

function Invoke-RestMethod {
    [CmdletBinding()]
    param(
        [string]$Uri,
        [string]$Method,
        [hashtable]$Headers,
        [string]$ContentType,
        [byte[]]$Body
    )
    $global:GatewayMockCalls += 1

    if ($Uri -ne 'http://127.0.0.1:8787/v1/chat/completions') {
        throw 'Unexpected destination URI'
    }
    if ($Method -ne 'Post') {
        throw 'Unexpected method'
    }
    if ($ContentType -ne 'application/json; charset=utf-8') {
        throw 'Content-Type did not explicitly declare UTF-8'
    }
    if ($Headers.Authorization -ne 'Bearer fixture-local-random-32-chars-abcdef') {
        throw 'Bearer key was not loaded correctly'
    }
    $decoded = [System.Text.Encoding]::UTF8.GetString($Body)
    $request = ConvertFrom-Json -InputObject $decoded
    if ($request.model -ne 'clickup-ui-current') {
        throw 'Incorrect model'
    }
    if ($request.messages[0].content -cne $global:GatewayMockExpectedPrompt) {
        throw 'Unicode prompt lost during JSON transport'
    }
    if ((-not ($Body -contains [byte]0xC3)) -or
        (-not ($Body -contains [byte]0xA0))) {
        throw 'Expected multibyte UTF-8 codepoint not found'
    }
    return @{ choices = @(@{ message = @{ content = 'OK' } }) }
}

$keyPath = Join-Path $env:TEMP ('brain-gateway-test-' + [guid]::NewGuid().ToString('N') + '.key')
try {
    'fixture-local-random-32-chars-abcdef' | Set-Content -LiteralPath $keyPath -Encoding Ascii
    $toolPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools\send_gateway_request.ps1'
    $answer = & $toolPath -KeyFile $keyPath -Prompt $global:GatewayMockExpectedPrompt -Port 8787
    if ($global:GatewayMockCalls -ne 1) {
        throw 'Expected exactly one mocked HTTP call'
    }
    if ($answer -cne 'OK') {
        throw 'Gateway reply was not parsed correctly'
    }
    Write-Host 'PASS: Windows PowerShell UTF-8 JSON bytes and mocked gateway API response'
}
finally {
    Remove-Item -LiteralPath $keyPath -ErrorAction SilentlyContinue
}
