# Langkah 38 lanjutan: ui.preview_fps 10 (keputusan desain pengguna; docs/UI-PREVIEW-OPT.md amandemen 2).
#
# Berurutan, --min-free-gb 2.5, daya AC (dicek ui_bench.require_ac). K2 (--disable-gpu-compositing)
# datang dari browser.py (pratinjau bukan off), jadi kondisi tanpa edge= tambahan.
#   (a) 07-fps10-vs-fps5   info: fps10 vs fps5, 10+10 selang-seling, tanpa keputusan
#   (b) 08-grow-fps10-gc   uji tumbuh 15 menit fps10 (sampel 30 s), lalu GC paksa di renderer
#                          (DevTools, seperti L31) dan RAM renderer +30/+60 s
#   (c) 09-camera-rate     laju kamera asli (+ YOLO asli) lalu sumber palsu; sanggup bila
#                          frame terbaca/s >= ui.preview_fps. Hanya dilaporkan, tidak menghentikan.
# stderr setiap proses anak bench dan console.log ada di folder tiap tahap. Tidak ada pengulangan
# otomatis: tahap (a)/(b) gagal -> skrip berhenti dengan pesan dan kode keluar bukan 0.
#
# Jalankan dari akar repo:
#   powershell -ExecutionPolicy Bypass -File scripts\l38_fps10.ps1
# Uji kering (tanpa bench dan tanpa kamera asli; folder sementara, 1 ulangan):
#   powershell -ExecutionPolicy Bypass -File scripts\l38_fps10.ps1 -DryRun

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
$Rate = Join-Path $Root "scripts\camera_rate.py"
if (-not (Test-Path $Py)) { Write-Host "BERHENTI: $Py tidak ada"; exit 2 }

$Fps5 = "fps5:static=21e25ae,preview=public,fps=5"
$Fps10 = "fps10:static=21e25ae,preview=public,fps=10"
if ($DryRun) {
    $Reps = 1
    $OutRoot = Join-Path $env:TEMP ("l38-fps10-dryrun-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
if (-not [IO.Path]::IsPathRooted($OutRoot)) { $OutRoot = Join-Path $Root $OutRoot }
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
New-Item -ItemType Directory -Force $OutRoot | Out-Null
$Log = Join-Path $OutRoot "l38_fps10.log"

function Say([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Stop-Run([string]$stage, [int]$code) {
    $why = switch ($code) {
        4 { "memori tersedia di bawah $MinFreeGb GB (penjaga memori); lihat aborted.json. Tutup aplikasi lain sebelum menjalankan tahap ini lagi." }
        5 { "proses anak bench berhenti sendiri; lihat aborted.json dan stderr-*.log." }
        default { "galat (kode $code); lihat console.log di folder tahap." }
    }
    Say "BERHENTI pada tahap $stage : $why"
    Say "Tidak ada yang dijalankan ulang otomatis. Tahap berikutnya tidak dijalankan."
    exit $code
}

function New-StageDir([string]$dir) {
    $out = Join-Path $OutRoot $dir
    if (-not $DryRun -and (Test-Path $out) -and (Get-ChildItem -Force $out | Select-Object -First 1)) {
        Say "BERHENTI: folder $out tidak kosong; hasil lama tidak ditimpa."
        exit 3
    }
    New-Item -ItemType Directory -Force $out | Out-Null
    return $out
}

function Invoke-Opt([string]$stage, [string]$dir, [string[]]$pyArgs) {
    $out = New-StageDir $dir
    $all = @($Opt) + $pyArgs + @("--out", $out, "--log", (Join-Path $out "console.log"))
    if ($DryRun) { $all += "--dry-run" }
    Say "MULAI $stage -> $out"
    & $Py @all | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Run $stage $LASTEXITCODE }
    Say "OK $stage"
    return $out
}

function Get-Json([string]$path) {
    if (Test-Path $path) { return Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json }
    return $null
}

Say ("Langkah 38 fps10: OutRoot={0} Reps={1} MinFreeGb={2} DryRun={3}" -f $OutRoot, $Reps, $MinFreeGb, [bool]$DryRun)

# (a) info: fps10 vs fps5
$dirA = Invoke-Opt "(a) fps10 vs fps5" "07-fps10-vs-fps5" @("ab", "--a", $Fps5, "--b", $Fps10, "--no-decision", "--reps", "$Reps", "--min-free-gb", "$MinFreeGb")

# (b) uji tumbuh 15 menit fps10 + GC paksa
$minutes = if ($DryRun) { "1" } else { "15" }
$dirB = Invoke-Opt "(b) uji tumbuh 15 menit fps10 + GC" "08-grow-fps10-gc" @("grow", "--condition", $Fps10, "--minutes", $minutes, "--interval", "30", "--cdp-gc", "--min-free-gb", "$MinFreeGb")

# (c) laju kamera: asli lalu palsu (hanya dilaporkan)
$dirC = New-StageDir "09-camera-rate"
$rateLog = Join-Path $dirC "console.log"
$runs = New-Object System.Collections.ArrayList
if ($DryRun) {
    Say "[dry-run] kamera asli TIDAK dibuka; perintahnya: $Py $Rate --seconds 30 --out $dirC"
    [void]$runs.Add(@("--fake", "--seconds", "2"))
} else {
    [void]$runs.Add(@("--seconds", "30"))
    [void]$runs.Add(@("--fake", "--seconds", "30"))
}
foreach ($r in $runs) {
    Say ("MULAI (c) laju kamera {0}" -f ($r -join " "))
    # stdout ke console.log; stderr (peringatan library) hanya ke layar
    & $Py $Rate @r --out $dirC | Tee-Object -FilePath $rateLog -Append | Out-Host
    Say ("(c) kode keluar {0} (0 = sanggup, 1 = tidak sanggup/galat; tidak menghentikan skrip)" -f $LASTEXITCODE)
}

# ringkasan
$summary = @("SELESAI")
$s = Get-Json (Join-Path $dirA "summary.json")
if ($null -ne $s) {
    $summary += "(a) fps10 vs fps5 (info):"
    foreach ($n in @("fps5", "fps10")) {
        $m = $s.summary.$n
        $summary += ("  {0}: RAM {1:N1} MB ({2:N1}-{3:N1}) | CPU {4:N2}% ({5:N2}-{6:N2}) | p95 {7:N2} ms ({8:N2}-{9:N2})" -f `
            $n, $m.uss.median, $m.uss.min, $m.uss.max, $m.cpu.median, $m.cpu.min, $m.cpu.max, `
            $m.p95.median, $m.p95.min, $m.p95.max)
    }
} else { $summary += "(a) (tidak ada summary.json: dry-run)" }
$g = Get-Json (Join-Path $dirB "summary.json")
if ($null -ne $g) {
    $summary += "(b) uji tumbuh fps10:"
    foreach ($p in $g.per_metric.PSObject.Properties) {
        $summary += ("  {0}: {1:N1} -> {2:N1} MB, kemiringan {3:+0.000;-0.000} MB/menit, {4}" -f `
            $p.Name, $p.Value.first5, $p.Value.last5, $p.Value.slope_mb_per_min, $p.Value.verdict)
    }
    if ($g.gc.error) { $summary += "  GC gagal: $($g.gc.error)" }
    elseif ($g.gc) {
        $summary += ("  GC renderer: {0:N1} MB -> +30 s {1:N1} MB -> +60 s {2:N1} MB: {3}" -f `
            $g.gc.renderer_before_mb, $g.gc.renderer_after_30s_mb, $g.gc.renderer_after_60s_mb, $g.gc.verdict)
    }
} else { $summary += "(b) (tidak ada summary.json: dry-run)" }
foreach ($f in @("camera_rate.json", "camera_rate-fake.json")) {
    $c = Get-Json (Join-Path $dirC $f)
    if ($null -eq $c) { $summary += "(c) ${f}: tidak ada"; continue }
    if ($c.error) { $summary += "(c) ${f}: $($c.error)"; continue }
    $summary += ("(c) {0}: frame {1:N2}/s, JPEG pratinjau {2:N2}/s, deteksi {3:N2}/s, sanggup={4}" -f `
        $f, $c.camera_read_fps, $c.preview_jpeg_fps, $c.detect_fps, $c.camera_capable)
}
$summary += "Hasil: $OutRoot"
foreach ($line in $summary) { Say $line }
