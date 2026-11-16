<#
.SYNOPSIS
    Gestionnaire Windows 11 ARM64 des serveurs locaux llama.cpp (LLM port 8081 & Embeddings port 8082)
    pour VeriteFiscale-2027 sur NVIDIA RTX Spark (128 Go LPDDR5X unifiee).

.DESCRIPTION
    Decouple strictement l'inference IA locale derriere des endpoints HTTP OpenAI-compatibles :
      - Port 8081 : Moteur LLM MoE (NVIDIA-Nemotron-3.5-Lightning-30B-A3B ou Qwen3.8-Flash-Next / Bolt)
      - Port 8082 : Moteur RAG Embeddings (EmbeddingGemma 2 GGUF en Q8_0 ou BF16 -- JAMAIS FP16)

    Respecte la regle RTX Spark : privilégie les modèles MoE rapides (3B-9B actifs)
    et refuse explicitement toute quantification/cache FP16 sur EmbeddingGemma 2 (risque de NaN).

.EXAMPLE
    .\scripts\windows\start_local_ai.ps1 -Mode Check
.EXAMPLE
    .\scripts\windows\start_local_ai.ps1 -Mode StartLLM -LlmAlias nemotron
.EXAMPLE
    .\scripts\windows\start_local_ai.ps1 -Mode StartEmbedding -EmbeddingModelPath "C:\AI\models\embeddinggemma-2-Q8_0.gguf"
.EXAMPLE
    .\scripts\windows\start_local_ai.ps1 -Mode StartAll -EmbeddingModelPath "C:\AI\models\embeddinggemma-2-Q8_0.gguf"
#>
[CmdletBinding()]
param(
    [ValidateSet('Check', 'StartLLM', 'StartEmbedding', 'StartAll')]
    [string]$Mode = 'Check',

    [ValidateSet('nemotron', 'flash-next', 'custom')]
    [string]$LlmAlias = 'nemotron',

    [string]$LlmModelPath = '',
    [string]$LlmMmprojPath = '',
    [int]$LlmPort = 8081,
    [int]$LlmContext = 131072,

    [string]$EmbeddingModelPath = '',
    [int]$EmbeddingPort = 8082,
    [int]$EmbeddingContext = 8192,
    [string]$EmbeddingCacheType = 'q8_0',

    [int]$GpuLayers = 999,
    [string]$ServerExe = 'C:\llama.cpp\llama-server.exe',
    [string]$FfmpegExe = 'C:\AI\jarvis\ffmpeg\ffmpeg-n8.1-latest-winarm64-gpl-shared-8.1\bin\ffmpeg.exe'
)

$ErrorActionPreference = 'Stop'

function Find-CachedGguf {
    param([string[]]$Patterns)
    $roots = @(
        (Join-Path $env:USERPROFILE '.cache\huggingface\hub'),
        'C:\AI\models',
        'C:\AI\jarvis\models'
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($pattern in $Patterns) {
            $match = Get-ChildItem -Path $root -Filter $pattern -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -notmatch '0000[2-9]-of-' } |
                Select-Object -First 1
            if ($match) { return $match.FullName }
        }
    }
    return $null
}

function Assert-SafeEmbeddingConfig {
    param(
        [string]$ModelFile,
        [string]$CacheType
    )
    if ($CacheType.ToLowerInvariant() -match '^(f16|fp16)$') {
        throw "BLOQUE : --cache-type '$CacheType' interdit sur EmbeddingGemma 2 (risque de NaN en FP16). Utiliser 'q8_0' ou 'bf16'."
    }
    if ($CacheType.ToLowerInvariant() -notin @('q8_0', 'bf16')) {
        throw "Type de cache non recommande pour EmbeddingGemma 2 : '$CacheType'. Valeurs autorisees : 'q8_0', 'bf16'."
    }
    if ($ModelFile -and ($ModelFile -match '(?i)(^|[-_])(f16|fp16)([-_.]|$)')) {
        throw "BLOQUE : Le fichier GGUF '$ModelFile' semble etre en FP16. EmbeddingGemma 2 doit etre execute en Q8_0 ou BF16 uniquement (risque de NaN)."
    }
}

function Resolve-LlmSelection {
    if ($LlmModelPath) {
        if (-not (Test-Path -LiteralPath $LlmModelPath -PathType Leaf)) {
            throw "Fichier GGUF LLM introuvable : $LlmModelPath"
        }
        return [pscustomobject]@{ Model = $LlmModelPath; Mmproj = $LlmMmprojPath; Alias = 'custom' }
    }
    if ($LlmAlias -eq 'nemotron') {
        $model = Find-CachedGguf -Patterns @('*Nemotron-3.5-Lightning-30B-A3B*.gguf', '*Nemotron-3.5-Bolt*.gguf')
        return [pscustomobject]@{ Model = $model; Mmproj = $null; Alias = 'nemotron-3.5-lightning' }
    }
    if ($LlmAlias -eq 'flash-next') {
        $model = Find-CachedGguf -Patterns @('Qwen3.8-Flash-Next*-00001-of-*.gguf', 'Qwen3.8-Flash-Next*.gguf')
        $mmproj = $null
        if ($model) {
            $parentSnap = Split-Path (Split-Path $model -Parent) -Parent
            $mmCandidate = Get-ChildItem -Path $parentSnap -Filter 'mmproj*.gguf' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($mmCandidate) { $mmproj = $mmCandidate.FullName }
        }
        return [pscustomobject]@{ Model = $model; Mmproj = $mmproj; Alias = 'qwen3.8-flash-next' }
    }
    return [pscustomobject]@{ Model = $null; Mmproj = $null; Alias = $LlmAlias }
}

function Resolve-EmbeddingSelection {
    if ($EmbeddingModelPath) {
        if (-not (Test-Path -LiteralPath $EmbeddingModelPath -PathType Leaf)) {
            throw "Fichier GGUF EmbeddingGemma 2 introuvable : $EmbeddingModelPath"
        }
        return $EmbeddingModelPath
    }
    return (Find-CachedGguf -Patterns @('*embeddinggemma-2*Q8_0*.gguf', '*embeddinggemma-2*BF16*.gguf', '*embeddinggemma*gguf'))
}

function Test-PortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    return ($null -ne $conn)
}

function Build-LlmArgs {
    param([string]$ModelPath, [string]$MmprojPath, [string]$AliasName)
    $args = @(
        '--model', $ModelPath,
        '--alias', $AliasName,
        '--host', '127.0.0.1',
        '--port', "$LlmPort",
        '--ctx-size', "$LlmContext",
        '--parallel', '1',
        '-ngl', "$GpuLayers",
        '--flash-attn', 'on',
        '--jinja',
        '--cache-type-k', 'q8_0',
        '--cache-type-v', 'q8_0',
        '--batch-size', '2048',
        '--ubatch-size', '512'
    )
    if ($MmprojPath -and (Test-Path -LiteralPath $MmprojPath -PathType Leaf)) {
        $args += @('--mmproj', $MmprojPath)
    }
    return $args
}

function Build-EmbeddingArgs {
    param([string]$ModelPath)
    return @(
        '--model', $ModelPath,
        '--alias', 'embeddinggemma-2',
        '--host', '127.0.0.1',
        '--port', "$EmbeddingPort",
        '--embeddings',
        '--pooling', 'mean',
        '--ctx-size', "$EmbeddingContext",
        '--parallel', '1',
        '-ngl', "$GpuLayers",
        '--cache-type-k', $EmbeddingCacheType,
        '--cache-type-v', $EmbeddingCacheType,
        '--batch-size', '2048',
        '--ubatch-size', '512'
    )
}

# --- Verification de securite sur la config embeddings ---
Assert-SafeEmbeddingConfig -ModelFile $EmbeddingModelPath -CacheType $EmbeddingCacheType

$llmInfo = Resolve-LlmSelection
$embGguf = Resolve-EmbeddingSelection
$hasLlama = Test-Path -LiteralPath $ServerExe -PathType Leaf
$hasFfmpeg = Test-Path -LiteralPath $FfmpegExe -PathType Leaf

if ($Mode -eq 'Check') {
    Write-Host '=== VeriteFiscale-2027 :: Diagnostic IA Locale & Binaires Windows 11 ARM64 ===' -ForegroundColor Cyan
    Write-Host ("Architecture OS     : {0}" -f $env:PROCESSOR_ARCHITECTURE)
    Write-Host ("llama-server.exe    : {0} ({1})" -f $ServerExe, $(if ($hasLlama) { 'OK' } else { 'MANQUANT' }))
    if ($hasLlama) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $ver = & $ServerExe --version 2>&1 | ForEach-Object { $_.ToString() } | Select-Object -First 2
        $ErrorActionPreference = $prevEap
        Write-Host ("  -> Version        : {0}" -f ($ver -join ' | '))
    }
    Write-Host ("ffmpeg.exe (ARM64)  : {0} ({1})" -f $FfmpegExe, $(if ($hasFfmpeg) { 'OK' } else { 'MANQUANT' }))

    foreach ($tool in @('uv', 'node', 'git', 'codex')) {
        $cmd = Get-Command $tool -ErrorAction SilentlyContinue
        Write-Host ("{0,-19} : {1}" -f $tool, $(if ($cmd) { $cmd.Source } else { 'NON TROUVE' }))
    }

    Write-Host "`n--- Modeles MoE & Embeddings detectes ---" -ForegroundColor Cyan
    Write-Host ("LLM ({0}) : {1}" -f $llmInfo.Alias, $(if ($llmInfo.Model) { $llmInfo.Model } else { 'NON DETECTE' }))
    if ($llmInfo.Mmproj) {
        Write-Host ("  -> mmproj Vision  : {0}" -f $llmInfo.Mmproj)
    }

    if ($embGguf) {
        Assert-SafeEmbeddingConfig -ModelFile $embGguf -CacheType $EmbeddingCacheType
        Write-Host ("EmbeddingGemma2 GGUF: {0}" -f $embGguf)
    } elseif (Test-Path -LiteralPath 'C:\AI\jarvis\models\embeddinggemma-2\model.safetensors') {
        Write-Host 'EmbeddingGemma2 GGUF: NON DETECTE (poids safetensors presents dans C:\AI\jarvis\models\embeddinggemma-2)' -ForegroundColor Yellow
        Write-Host '  -> Action recommandee : telecharger le GGUF Q8_0 (jamais FP16) depuis ggml-org/embeddinggemma-2-GGUF' -ForegroundColor Yellow
        Write-Host '     ex: hf download ggml-org/embeddinggemma-2-GGUF --include "*Q8_0*.gguf" --local-dir C:\AI\models\embeddinggemma-2-gguf' -ForegroundColor DarkGray
    } else {
        Write-Host 'EmbeddingGemma2 GGUF: NON DETECTE' -ForegroundColor Yellow
    }

    Write-Host "`n--- Ports reseau locaux ---" -ForegroundColor Cyan
    Write-Host ("Port {0} (LLM)      : {1}" -f $LlmPort, $(if (Test-PortListening $LlmPort) { 'EN ECOUTE' } else { 'Libre (arrete)' }))
    Write-Host ("Port {0} (Embed)    : {1}" -f $EmbeddingPort, $(if (Test-PortListening $EmbeddingPort) { 'EN ECOUTE' } else { 'Libre (arrete)' }))
    Write-Host ("Port 9931 (Router)  : {0}" -f $(if (Test-PortListening 9931) { 'EN ECOUTE (routeur RTX Spark actif)' } else { 'Libre' }))
    exit 0
}

if (-not $hasLlama) {
    throw "llama-server.exe introuvable a l'emplacement : $ServerExe"
}

if ($Mode -eq 'StartLLM') {
    if (-not $llmInfo.Model) {
        throw "Aucun modele GGUF MoE trouve pour l'alias '$LlmAlias'. Specifiez -LlmModelPath."
    }
    if (Test-PortListening $LlmPort) {
        throw "Le port $LlmPort est deja occupe."
    }
    $launchArgs = Build-LlmArgs -ModelPath $llmInfo.Model -MmprojPath $llmInfo.Mmproj -AliasName $llmInfo.Alias
    Write-Host "Demarrage LLM sur http://127.0.0.1:$LlmPort/v1 ($($llmInfo.Alias))..." -ForegroundColor Green
    & $ServerExe @launchArgs
    exit $LASTEXITCODE
}

if ($Mode -eq 'StartEmbedding') {
    if (-not $embGguf) {
        throw "Aucun fichier GGUF EmbeddingGemma 2 trouve. Telechargez ggml-org/embeddinggemma-2-GGUF (Q8_0 ou BF16, jamais FP16) et passez -EmbeddingModelPath."
    }
    Assert-SafeEmbeddingConfig -ModelFile $embGguf -CacheType $EmbeddingCacheType
    if (Test-PortListening $EmbeddingPort) {
        throw "Le port $EmbeddingPort est deja occupe."
    }
    $launchArgs = Build-EmbeddingArgs -ModelPath $embGguf
    Write-Host "Demarrage EmbeddingGemma 2 ($EmbeddingCacheType) sur http://127.0.0.1:$EmbeddingPort/v1..." -ForegroundColor Green
    & $ServerExe @launchArgs
    exit $LASTEXITCODE
}

if ($Mode -eq 'StartAll') {
    if (-not $llmInfo.Model) { throw "Aucun modele LLM GGUF trouve." }
    if (-not $embGguf) { throw "Aucun modele EmbeddingGemma 2 GGUF trouve (Q8_0/BF16 requis)." }
    Assert-SafeEmbeddingConfig -ModelFile $embGguf -CacheType $EmbeddingCacheType
    if (Test-PortListening $LlmPort) { throw "Port LLM $LlmPort deja occupe." }
    if (Test-PortListening $EmbeddingPort) { throw "Port Embeddings $EmbeddingPort deja occupe." }

    $llmArgs = Build-LlmArgs -ModelPath $llmInfo.Model -MmprojPath $llmInfo.Mmproj -AliasName $llmInfo.Alias
    $embArgs = Build-EmbeddingArgs -ModelPath $embGguf

    $pLlm = Start-Process -FilePath $ServerExe -ArgumentList $llmArgs -PassThru
    $pEmb = Start-Process -FilePath $ServerExe -ArgumentList $embArgs -PassThru
    Write-Host "LLM PID=$($pLlm.Id) -> http://127.0.0.1:$LlmPort/v1" -ForegroundColor Green
    Write-Host "EMB PID=$($pEmb.Id) -> http://127.0.0.1:$EmbeddingPort/v1" -ForegroundColor Green
    exit 0
}
