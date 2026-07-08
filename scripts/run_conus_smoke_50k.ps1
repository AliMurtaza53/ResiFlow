# CONUS smoke: 50k combined OD pairs, freight + passenger, 2 assignment iterations.
# Run from ResiFlow repo root.

param(
    [int]$DepthKey = 30,
    [int[]]$EventKeys = @(1, 2, 3),
    [int]$NumChunks = 20,
    [int]$NumCpu = 1,
    [int]$MaxFlowIterations = 2,
    [int]$SampleOdN = 50000,
    [string]$ResultsVariant = "smoke_50k",
    [string]$Python = "$env:LOCALAPPDATA\miniforge3\envs\nird\python.exe",
    [int]$LodesYear = 2022
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python"
}

$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$config = Get-Content (Join-Path $repoRoot "config.json") -Raw | ConvertFrom-Json
$basePath = $config.paths.soge_clusters
$resultsRoot = Join-Path (Split-Path -Parent $basePath) "results"
$damagedEdgesPath = Join-Path $basePath "tables\event_damaged_edges_depth${DepthKey}_toy.pq"
$lodesAssignment = Join-Path (Split-Path -Parent $basePath) `
    "lodes_data\processed\lodes_passenger_assignment_od_jt00_$LodesYear.parquet"
$hazardDir = Join-Path $basePath "inputs\test_141node_50m"

function Invoke-Step([string]$Name, [string[]]$StepArgs) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $log = Join-Path $logDir "$ts`_$Name.log"
    Write-Host ""
    Write-Host "==== $Name ===="
    Write-Host "$Python $($StepArgs -join ' ')"
    Write-Host "Log: $log"
    $oldErrorActionPreference = $ErrorActionPreference
    $oldNativePreference = $null
    $hasNativePreference = Test-Path Variable:\PSNativeCommandUseErrorActionPreference
    if ($hasNativePreference) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $ErrorActionPreference = "Continue"
        & $Python @StepArgs *>&1 | Tee-Object -FilePath $log
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
    if ($exitCode -ne 0) {
        throw "$Name failed (exit $exitCode). See $log"
    }
    return $log
}

function Set-SmokeEnv {
    $env:RESIFLOW_CONFIG_PATH = Join-Path $repoRoot "config.json"
    $env:RESIFLOW_RESULTS_VARIANT = $ResultsVariant
    $env:NIRD_RESULTS_VARIANT = $ResultsVariant

    $env:RESIFLOW_MAX_FLOW_ITERATIONS = "$MaxFlowIterations"
    $env:NIRD_MAX_FLOW_ITERATIONS = "$MaxFlowIterations"
    $env:RESIFLOW_SAMPLE_OD_N = "$SampleOdN"
    $env:NIRD_SAMPLE_OD_N = "$SampleOdN"

    $env:NIRD_PATH_REALIZATION_STRATEGY = "streaming_arrays"
    $env:NIRD_DIRECT_DUCKDB_OUTPUTS = "1"
    $env:NIRD_CREATE_FULL_TEMP_FLOW_MATRIX = "0"
    $env:NIRD_ODPFC_OUTPUT_MODE = "skip"
    $env:NIRD_WRITE_FULL_ODPFC = "0"
    $env:NIRD_COMBINE_EVENT_CANDIDATE_PARTS = "0"
    $env:NIRD_ENABLE_SPLIT_CACHE = "1"
    $env:NIRD_VECTORIZE_PATH_PARSING = "1"
    $env:NIRD_OD_ID_AT_INSERT = "1"
    $env:OMP_NUM_THREADS = "1"
    $env:MKL_NUM_THREADS = "1"
    $env:OPENBLAS_NUM_THREADS = "1"

    if (-not (Test-Path -LiteralPath $lodesAssignment)) {
        throw "Passenger OD missing: $lodesAssignment"
    }
    $env:NIRD_PASSENGER_OD_PATH = $lodesAssignment
    $env:RESIFLOW_PASSENGER_OD_PATH = $lodesAssignment
    $env:NIRD_ENABLE_PASSENGER_REROUTING = "1"
    $env:RESIFLOW_ENABLE_PASSENGER_REROUTING = "1"
    Remove-Item Env:RESIFLOW_DISABLE_PASSENGER_OD -ErrorAction SilentlyContinue
    Remove-Item Env:NIRD_DISABLE_PASSENGER_OD -ErrorAction SilentlyContinue
}

$required = @(
    (Join-Path $basePath "networks\faf5\faf5_road_links.gpq"),
    (Join-Path $basePath "census_datasets\faf5_od_matrix.pq"),
    (Join-Path $hazardDir "va_hazard_class50_141node_base.tif"),
    (Join-Path $basePath "tables\recovery design_updated.csv"),
    $lodesAssignment
)
foreach ($p in $required) {
    if (-not (Test-Path -LiteralPath $p)) { throw "Missing prerequisite: $p" }
}

Write-Host "CONUS smoke_50k (freight + passenger)"
Write-Host "  Variant:   $ResultsVariant"
Write-Host "  Sample OD: $SampleOdN"
Write-Host "  Max iters: $MaxFlowIterations"

Set-SmokeEnv

Write-Host "Normalizing toy hazard CRS (metadata-only)..."
Invoke-Step "normalize_hazard_crs" @(
    "scripts/normalize_hazard_crs.py",
    "--input-dir", $hazardDir,
    "--in-place"
)

$candidateRoot = Join-Path $resultsRoot "base_scenario\$ResultsVariant\event_disrupted_candidates"
if (Test-Path -LiteralPath $candidateRoot) {
    Remove-Item -LiteralPath $candidateRoot -Recurse -Force
}

Remove-Item Env:NIRD_EVENT_DAMAGED_EDGES_PATH -ErrorAction SilentlyContinue
Remove-Item Env:NIRD_BASELINE_PATH_OUTPUT_MODE -ErrorAction SilentlyContinue
Invoke-Step "passA_script1" @("scripts/1_network_flow_model_revision.py", "$NumChunks", "$NumCpu")

foreach ($ek in $EventKeys) {
    Invoke-Step "script2_event$ek" @("scripts/2_intersection_analysis.py", "$DepthKey", "$ek")
}

$exportArgs = @(
    "scripts/export_event_damaged_edges.py",
    "--depth-key", "$DepthKey",
    "--event-keys"
) + ($EventKeys | ForEach-Object { "$_" }) + @(
    "--output", $damagedEdgesPath,
    "--results-variant", $ResultsVariant
)
Invoke-Step "export_event_damaged_edges" $exportArgs

Invoke-Step "script3_damage" @("scripts/3_damage_analysis.py")
Invoke-Step "script3_postprocess" @("scripts/3_postprocess_damage.py")

$env:NIRD_BASELINE_PATH_OUTPUT_MODE = "event_candidates"
$env:NIRD_EVENT_DAMAGED_EDGES_PATH = $damagedEdgesPath
Invoke-Step "passB_script1" @("scripts/1_network_flow_model_revision.py", "$NumChunks", "$NumCpu")

foreach ($ek in $EventKeys) {
    Invoke-Step "script4_event$ek" @(
        "scripts/4_rerouting_and_recovery_scenario_loop.py",
        "$DepthKey", "$ek", "$NumChunks", "$NumCpu"
    )
}

Write-Host ""
Write-Host "Workflow completed successfully."
Write-Host "Results: $resultsRoot (variant=$ResultsVariant)"
