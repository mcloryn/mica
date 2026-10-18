# Langkah 38: sisa pengukuran pratinjau kamera (pra-registrasi docs/UI-PREVIEW-OPT.md).
#
# Berurutan, semua --min-free-gb 2.5, selang-seling, daya AC (dicek ui_bench.require_ac):
#   (a) 03-k2-vs-base   K2 (--disable-gpu-compositing) vs pembanding (img, statis 21e25ae)
#   (b) decide          aturan pra-registrasi -> konfigurasi akhir (K2 bila lolos, pembanding bila tidak)
#       04-akhir-vs-off konfigurasi akhir vs pratinjau off (laporan, tanpa keputusan)
#   (c) 05-fps2-vs-fps5 info saja: preview_fps 2 vs 5 dengan konfigurasi akhir
#   (d) 06-grow-akhir   uji tumbuh 15 menit konfigurasi akhir, sampel tiap 30 s
# stderr setiap proses anak bench dan console.log ada di folder tiap tahap. Tidak ada pengulangan
# otomatis: tahap gagal -> skrip berhenti dengan pesan dan kode keluar bukan 0.
#
# Jalankan dari akar repo:
#   powershell -ExecutionPolicy Bypass -File scripts\l38_run_rest.ps1
# Uji kering (tanpa bench; folder sementara, 1 ulangan):
#   powershell -ExecutionPolicy Bypass -File scripts\l38_run_rest.ps1 -DryRun

param(
    [switch]$DryRun,
    [string]$OutRoot = "results\ADR-19\ui-preview-opt-20261018-1712",
    [int]$Reps = 10,
    [double]$MinFreeGb = 2.5
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = "utf-8"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Opt = Join-Path $Root "scripts\ui_preview_opt.py"
if (-not (Test-Path $Py)) { Write-Host "BERHENTI: $Py tidak ada"; exit 2 }

$Base = "base:static=21e25ae"
$K2 = "k2:static=21e25ae,edge=--disable-gpu-compositing"
$Off = "off:static=21e25ae,preview=off"
$DecideFrom = $null
if ($DryRun) {
    $Reps = 1
    $OutRoot = Join-Path $env:TEMP ("l38-dryrun-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
if (-not [IO.Path]::IsPathRooted($OutRoot)) { $OutRoot = Join-Path $Root $OutRoot }
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
New-Item -ItemType Directory -Force $OutRoot | Out-Null
if ($DryRun) {
    # salinan hasil K1 resmi, hanya untuk menguji jalur decide (folder 02 tidak disentuh)
    $src = Join-Path $Root "results\ADR-19\ui-preview-opt-20261018-1712\02-k1-vs-base"
    $copy = New-Item -ItemType Directory -Force (Join-Path $OutRoot "decide-uji-02")
    Copy-Item (Join-Path $src "summary.json"), (Join-Path $src "per_run.csv") $copy
    $DecideFrom = Join-Path $copy "summary.json"
}
$Log = Join-Path $OutRoot "l38_run_rest.log"

function Say([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Stop-Run([string]$stage, [int]$code) {
    $why = switch ($code) {
        4 { "memori tersedia di bawah $MinFreeGb GB (penjaga memori); lihat aborted.json. Tutup aplikasi lain sebelum menjalankan tahap ini lagi." }
        5 { "proses anak bench berhenti sendiri; lihat aborted.json dan stderr-*.log." }
        6 { "run K2 tidak lengkap, keputusan tidak bisa dibuat." }
        default { "galat (kode $code); lihat console.log di folder tahap." }
    }
    Say "BERHENTI pada tahap $stage : $why"
    Say "Tidak ada yang dijalankan ulang otomatis. Tahap berikutnya tidak dijalankan."
    exit $code
}

function Invoke-Opt([string]$stage, [string]$dir, [string[]]$pyArgs) {
    $out = Join-Path $OutRoot $dir
    if (-not $DryRun -and (Test-Path $out) -and (Get-ChildItem -Force $out | Select-Object -First 1)) {
        Say "BERHENTI: folder $out tidak kosong; hasil lama tidak ditimpa."
        exit 3
    }
    New-Item -ItemType Directory -Force $out | Out-Null
    $all = @($Opt) + $pyArgs + @("--out", $out, "--log", (Join-Path $out "console.log"))
    if ($DryRun) { $all += "--dry-run" }
    Say "MULAI $stage -> $out"
    & $Py @all | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Run $stage $LASTEXITCODE }
    Say "OK $stage"
    return $out
}

function Get-Summary([string]$dir) {
    $p = Join-Path $dir "summary.json"
    if (Test-Path $p) { return Get-Content -Raw -Encoding UTF8 $p | ConvertFrom-Json }
    return $null
}

function Format-Ab($s) {
    if ($null -eq $s) { return "  (tidak ada summary.json: dry-run)" }
    $lines = @()
    foreach ($n in @($s.a.name, $s.b.name)) {
        $m = $s.summary.$n
        $lines += ("  {0}: RAM {1:N1} MB ({2:N1}-{3:N1}) | CPU {4:N2}% ({5:N2}-{6:N2}) | p95 {7:N2} ms ({8:N2}-{9:N2})" -f `
            $n, $m.uss.median, $m.uss.min, $m.uss.max, $m.cpu.median, $m.cpu.min, $m.cpu.max, `
            $m.p95.median, $m.p95.min, $m.p95.max)
    }
    return ($lines -join "`n")
}

Say ("Langkah 38 sisa: OutRoot={0} Reps={1} MinFreeGb={2} DryRun={3}" -f $OutRoot, $Reps, $MinFreeGb, [bool]$DryRun)
$common = @("--reps", "$Reps", "--min-free-gb", "$MinFreeGb")

# (a) K2 vs pembanding
$dirA = Invoke-Opt "(a) K2 vs pembanding" "03-k2-vs-base" (@("ab", "--a", $Base, "--b", $K2) + $common)

# (b) keputusan K2 dengan aturan pra-registrasi, lalu akhir vs off
if ($null -eq $DecideFrom) { $DecideFrom = Join-Path $dirA "summary.json" }
Say "MULAI (b) keputusan dari $DecideFrom"
$decideOut = & $Py $Opt decide --summary $DecideFrom --log (Join-Path $dirA "console.log")
$code = $LASTEXITCODE
$decideOut | ForEach-Object { Write-Host $_ }
if ($code -ne 0) { Stop-Run "(b) keputusan" $code }
$Final = (($decideOut | Where-Object { $_ -like "FINAL=*" }) | Select-Object -Last 1) -replace "^FINAL=", ""
if (-not $Final) { Say "BERHENTI: decide tidak mencetak FINAL="; exit 7 }
Say "Konfigurasi akhir: $Final"

$dirB = Invoke-Opt "(b) akhir vs off" "04-akhir-vs-off" (@("ab", "--a", $Off, "--b", $Final, "--no-decision") + $common)

# (c) info saja: fps 2 vs 5 dengan konfigurasi akhir
$Fps5 = ($Final -replace "^akhir:", "fps5:") + ",fps=5"
$Fps2 = ($Final -replace "^akhir:", "fps2:") + ",fps=2"
$dirC = Invoke-Opt "(c) fps 2 vs 5" "05-fps2-vs-fps5" (@("ab", "--a", $Fps5, "--b", $Fps2, "--no-decision") + $common)

# (d) uji tumbuh 15 menit konfigurasi akhir
$dirD = Invoke-Opt "(d) uji tumbuh 15 menit" "06-grow-akhir" @("grow", "--condition", $Final, "--minutes", "15", "--interval", "30", "--min-free-gb", "$MinFreeGb")

# ringkasan
$summary = @("SELESAI", "Konfigurasi akhir: $Final")
$dec = Join-Path (Split-Path $DecideFrom) "decision.json"
if (Test-Path $dec) {
    $d = Get-Content -Raw -Encoding UTF8 $dec | ConvertFrom-Json
    $summary += ("(a) {0} vs {1}: {2}" -f $d.b.name, $d.a.name, $(if ($d.better) { "LOLOS" } else { "TIDAK LOLOS" }))
}
$summary += Format-Ab (Get-Summary $dirA)
$summary += "(b) akhir vs off:"
$summary += Format-Ab (Get-Summary $dirB)
$summary += "(c) fps 2 vs 5 (info):"
$summary += Format-Ab (Get-Summary $dirC)
$g = Get-Summary $dirD
if ($null -ne $g) {
    $summary += "(d) uji tumbuh 15 menit:"
    foreach ($p in $g.per_metric.PSObject.Properties) {
        $summary += ("  {0}: {1:N1} -> {2:N1} MB, kemiringan {3:+0.000;-0.000} MB/menit, {4}" -f `
            $p.Name, $p.Value.first5, $p.Value.last5, $p.Value.slope_mb_per_min, $p.Value.verdict)
    }
} else {
    $summary += "(d) uji tumbuh: (tidak ada summary.json: dry-run)"
}
$summary += "Hasil: $OutRoot"
foreach ($line in $summary) { Say $line }
