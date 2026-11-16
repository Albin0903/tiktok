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
2. Verifie le perimetre exact des pensions (retraite vs pensions alimentaires / invalidite), la separation horizon 'annee_1' vs 'regime_permanent', la boucle N-2 (max_spiral_loops) et la limite lissage CSG 2 ans.
3. Verifie l'indexation explicite par identifiants d'entites, la presence des commentaires '# SOURCE: ...' sur chaque constante/bareme et les attributs calc_certainty / legal_status conformes a DESIGN.md.
4. Contrainte d'execution en sandbox lecture seule (-s read-only) : n'utilise PAS 'uv run' (echec sur verrou du cache global uv). Execute directement les tests et scripts via le Python du venv local :
   - engine\.venv\Scripts\python.exe -m pytest -v engine/tests/
   - engine\.venv\Scripts\python.exe -m engine.reforms.demo_plf2027_retraites
5. Signale tout bug fiscal silencieux, cas limite manquant ou divergence potentielle avec impots.gouv.fr / LexImpact.
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
