# Langkah 40: profil waktu mulai aplikasi (scripts/startup_profile.py), kamera asli bila ada.
#
# 1 ulangan pemanasan (dibuang) + 5 ulangan, config dev + nilai coba SDD bagian 12, AC wajib.
# Tiap ulangan: python -m mica (check, pekerja kamera dan suara asli, pipeline asli, Edge kiosk)
# sampai "semua siap" atau batas waktu, lalu jendela Edge ditutup. Hasil di
# results\STARTUP\<tanggal-jam>-<Label>\. Tidak ada pengulangan otomatis; gagal -> berhenti.
#
#   powershell -ExecutionPolicy Bypass -File scripts\l40_startup.ps1 -Label sebelum
#   powershell -ExecutionPolicy Bypass -File scripts\l40_startup.ps1 -Label sebelum -DryRun
# Tanpa kamera: tambahkan -FakeCamera (kamera dan suara palsu, pipeline asli).
# Mulai dingin (tepat setelah restart laptop, 1 ulangan tanpa pemanasan):
#   powershell -ExecutionPolicy Bypass -File scripts\l40_startup.ps1 -Label dingin -Warmup 0 -Reps 1 -Note "mulai dingin: dijalankan tepat setelah restart laptop"

param(
    [Parameter(Mandatory = $true)][string]$Label,
    [int]$Reps = 5,
    [int]$Warmup = 1,
    [double]$TimeoutS = 420,
    [double]$MinFreeGb = 1.0,
    [string]$Note = "",
    [switch]$FakeCamera,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = "utf-8"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "BERHENTI: $Py tidak ada"; exit 2 }

$pyArgs = @("scripts\startup_profile.py", "--label", $Label, "--reps", "$Reps", "--warmup", "$Warmup",
            "--timeout", "$TimeoutS", "--min-free-gb", "$MinFreeGb")
if ($FakeCamera) { $pyArgs += "--fake-camera" }
if ($Note) { $pyArgs += @("--note", $Note) }
if ($DryRun) { $pyArgs += "--dry-run" }
Write-Host ("[{0}] MULAI profil waktu mulai: {1}" -f (Get-Date -Format "HH:mm:ss"), ($pyArgs -join " "))
& $Py @pyArgs
$code = $LASTEXITCODE
switch ($code) {
    0 { Write-Host "SELESAI" }
    4 { Write-Host "BERHENTI: memori tersedia di bawah $MinFreeGb GB; tutup aplikasi lain. Tidak dijalankan ulang otomatis." }
    5 { Write-Host "BERHENTI: aplikasi tidak mencapai 'semua siap' (lihat aborted.json, rep-*\stderr.log). Bila kamera tidak ada, jalankan lagi dengan -FakeCamera." }
    default { Write-Host "BERHENTI: galat (kode $code)." }
}
exit $code
