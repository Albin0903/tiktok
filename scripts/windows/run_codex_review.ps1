<#
.SYNOPSIS
    Lance un audit croise independant via Codex CLI (ChatGPT / Codex Plus) sur une reforme fiscale OpenFisca.

.EXAMPLE
    .\scripts\windows\run_codex_review.ps1 -TargetFile engine/reforms/demo_plf2027_retraites.py
#>
[CmdletBinding()]
param(
    [string]$TargetFile = 'engine/reforms/demo_plf2027_retraites.py',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$targetPath = Join-Path $repoRoot $TargetFile
if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
    throw "Fichier cible introuvable : $targetPath"
}

$codexCmd = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codexCmd) {
    throw "Codex CLI introuvable dans le PATH."
}

$reviewPrompt = @"
Effectue une revue fiscale et technique rigoureuse du fichier '$TargetFile' selon AGENTS.md :
1. Verifie les variables et parametres openfisca_france utilises (entite Individu vs FoyerFiscal vs Menage, periode MONTH vs YEAR, convention de signe IR/CSG negative).
2. Verifie la gestion de la boucle temporelle N-2 (RFR -> taux CSG retraites, max_spiral_loops) et les effets de seuil / decote / plafonnement foyer fiscal.
3. Verifie la presence des commentaires '# SOURCE: ...' sur chaque constante ou bareme.
4. Signale tout bug fiscal silencieux, cas limite manquant ou divergence potentielle avec impots.gouv.fr / LexImpact.
"@

if ($DryRun) {
    Write-Host "Codex executable : $($codexCmd.Source)" -ForegroundColor Cyan
    Write-Host "Cible            : $targetPath" -ForegroundColor Cyan
    Write-Host "`nPrompt d'audit croise :" -ForegroundColor Yellow
    Write-Host $reviewPrompt
    exit 0
}

Write-Host "Lancement de l'audit croise Codex CLI sur $TargetFile..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & $codexCmd.Source exec $reviewPrompt
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
