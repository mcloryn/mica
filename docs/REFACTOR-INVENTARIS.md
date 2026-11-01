# Inventaris refactor kiosk -> web app (Langkah 68)

Dibuat 1 Nov 2026 di branch `refactor/webapp`, dari tag `tahap1-beku` (commit 1a9b537). Isinya hanya
inventaris: belum ada kode yang diubah atau dihapus. Usulan di sini menunggu keputusan pemilik proyek.

Konteks: sejak bimbingan 22 Okt 2026, MICA bukan kiosk lagi. MICA sekarang web app di satu laptop PMB,
dibuka di browser dalam jendela biasa. Sistem Uji RAG Tahap 1 harus tetap bisa direproduksi dari tag
`tahap1-beku`.

## Cara inventaris dibuat

- K1: `grep -i kiosk` atas src/, config/, tests/, scripts/, docs/, README.md, .env.example, dan
  pyproject.toml. Satu baris tabel untuk satu baris file. Usulan diberi secara berurutan menurut aturan
  berikut: dokumen eksperimen/pra-reg -> biarkan; kode PySide6 -> hapus (K3); `KioskController`,
  `CFG_GEMINI_IN_KIOSK`, `kiosk.yaml`, nilai `app.mode`, dan identifier `*_kiosk*` -> ganti nama; sisanya
  -> ganti kata. Kolom "Isi sekarang" dipotong sampai 110 karakter.
- K4: semua definisi tingkat atas di src/mica (kecuali vision/) dicari pemakaiannya dengan grep kata utuh
  di src/, tests/, dan scripts/. Semua modul dicek apakah diimpor di src/. vulture tidak terpasang, jadi
  tidak dipakai.
- Di luar cakupan dan tidak diberi usulan: src/mica/vision/, data/, KB, prompt, gerbang, data/eval/, hasil
  run (results/), docs/SDD.md, docs/PRA-REGISTRASI-TAHAP1.md, dan D:\SKRIPSI\mica-cv.
  - Kata "kiosk" di src/mica/vision/ ada di **6 baris**: worker.py 4, livepreview.py 1, fakesource.py 1.
  - Untuk perbandingan: docs/SDD.md memuat "kiosk" 77 kali dan results/ 48 kali (salinan file statis lama
    dan run.json).
- Garis dasar pytest sebelum refactor (1 Nov 2026, tanpa perubahan kode): **1684 lulus, 0 gagal, 0 dilewati**
  (159 s).

## Temuan penting (dibaca sebelum refactor)

1. **SDD memakai nama-nama kiosk.** `KioskController` muncul 7 kali, `CFG_GEMINI_IN_KIOSK` 2 kali,
   `config/kiosk.yaml` 5 kali, dan PySide6 15 kali. CLAUDE.md mewajibkan nama kode sama persis dengan SDD.
   Karena itu SDD (dan CLAUDE.md, yang juga menyebut "mode kiosk") perlu diubah dulu atau bersamaan, lewat
   keputusan pemilik proyek.
2. **ADR-19 (`ui.backend`) berstatus Provisional** dan saat ini dipilih lewat config, sesuai aturan
   CLAUDE.md. Menghapus PySide6 berarti ADR-19 ditetapkan final ke web. Keputusan itu perlu dicatat di SDD.
3. **`mica.ui` tidak bisa dihapus utuh.** `mica.ui.viewmodel` dipakai oleh webui (server.py, state.py),
   oleh **eval/tahap1.py** (`source_line`), dan oleh 7 berkas tes. `mica.ui.devfakes` dipakai oleh webui/app.py,
   scripts/camera_rate.py, dan 5 berkas tes. Kedua modul ini bebas Qt dan perlu dipindah (misalnya ke
   `mica.core` atau `mica.webui`), tidak dihapus. Hanya app.py, main_window.py, dan `__main__.py` yang
   benar-benar terikat Qt.
4. **`Settings.config_hash()` mencakup seluruh config** (`model_dump` tanpa api_keys). Mengganti `app.mode`
   atau menghapus `ui.backend`/`ui.fullscreen` pasti mengubah hash. Hash di manifest Tahap 1 (17d5b6e5…)
   tidak akan cocok lagi, walaupun perilaku RAG sama. Bukti bahwa RAG tidak berubah harus lewat
   perbandingan hasil (bagian C), bukan lewat hash config.
5. **Siklus hidup aplikasi bergantung pada proses Edge.** webui/app.py `serve()` berhenti saat jendela Edge
   ditutup (`browser.alive()`), dan menutup Edge saat server berhenti. Browser bawaan yang dibuka dengan
   `webbrowser.open` tidak memberi PID, jadi butuh cara berhenti lain, misalnya Ctrl+C seperti
   `--no-browser`, atau tombol keluar. Ini perubahan perilaku, bukan sekadar ganti nama.
6. **Pengukuran E-09 mengandalkan PID Edge.** Kelompok proses "edge" di eval/resources.py,
   eval/preview_meter.py, dan eval/latency.py diambil dari `EdgeBrowser.pid`. Dengan browser bawaan,
   kelompok ini tidak bisa diukur dengan cara yang sama. Protokol E-09 dan docs/E-09.md ditulis untuk Edge
   kiosk.
7. **Edge masih dipakai alat dev.** `find_edge` dipakai oleh `test_js_formatter_matches_python` (uji
   kesetaraan answer_format.js lewat Edge headless; dilewati bila Edge tidak ada) dan oleh
   scripts/ui_screens.py. Bila browser.py dihapus utuh, keduanya ikut rusak.
8. **Sebagian tes web membandingkan web dengan PySide6.** 7 tes di test_webui.py memakai `qtbot`/MainWindow.
   Bila PySide6 dihapus, tes kesetaraan ini hilang, sehingga perilaku event UI web hanya dijaga tes web saja.
9. **Kode mati sungguhan hampir tidak ada.** Grep hanya menemukan 2 definisi yang tidak dipanggil dari src/,
   dan keduanya sengaja dibuat begitu (alat skrip dan versi acuan untuk tes). Sebagian besar "kode mati"
   baru muncul setelah PySide6 dan Edge dibuang (K3/K2).
10. **Dokumen eksperimen ikut memakai kata kiosk.** docs/E-0x, UI-WEB, UI-PREVIEW-OPT, CPU-THREADS, PROMPT-V3/V4,
    dan lainnya adalah pra-registrasi atau catatan eksperimen. Usulannya: biarkan, karena menggambarkan
    kondisi saat itu, dan tambahkan catatan di README. docs/KIOSK.md adalah panduan pemasangan yang usang
    dan perlu ditulis ulang.

## Jumlah baris per kategori

| Kategori | Baris | Keterangan |
|---|---|---|
| K1 kata "kiosk" | 467 | 59 biarkan (dokumen eksperimen), 37 ikut terhapus bersama PySide6, 28 juga terkait Edge, sisanya ganti nama/kata |
| K2 peluncur Edge | 16 | |
| K3 PySide6 | 22 | |
| K4 kode mati | 6 | 2 hasil grep (biarkan), 4 calon yang baru mati setelah K2/K3 |
| K5 file usang | 13 | hanya ditandai |


## K2. Peluncur Microsoft Edge

Usulan umum: aplikasi membuka browser bawaan dalam jendela biasa (pustaka standar `webbrowser`, tanpa
dependensi baru) dan berhenti lewat Ctrl+C atau tombol keluar. `find_edge` dipertahankan hanya untuk alat dev
(lihat temuan 7).

| No | Lokasi (file:baris) | Isi sekarang | Kategori | Usulan (ganti nama / hapus / biarkan) | Risiko |
|---|---|---|---|---|---|
| K2-1 | `src/mica/webui/browser.py:1-143` | `EdgeBrowser`, `edge_command` (`--kiosk <url> --edge-kiosk-type=fullscreen`, `--user-data-dir`), `RENDERING_SWITCHES`, `IDLE_SWITCHES`, `PREVIEW_SWITCHES`, `find_edge`, `EDGE_PATHS` | K2 | ganti isi: peluncur browser bawaan. Hapus `edge_command`/`EdgeBrowser`/switch; `find_edge`/`EDGE_PATHS`/`EdgeMissing` dipindah ke alat dev atau dibiarkan | sedang: switch hasil optimasi RAM/CPU (ADR-19, Langkah 31/38) hilang; browser bawaan tidak bisa diberi switch. Tes ikut terhapus: test_edge_command_flags, test_production_browser_never_opens_devtools_port, test_preview_switch_only_when_preview_on, test_rendering_switches_are_only_verified_ones, test_edge_browser_with_fake_popen |
| K2-2 | `src/mica/webui/app.py:145-183` | `serve()` menunggu `browser.alive()`; jendela Edge ditutup -> server berhenti; server berhenti -> `browser.close()` | K2 | ganti: berhenti lewat Ctrl+C/tombol keluar; tidak memantau jendela browser | tinggi: perilaku berhenti berubah. Tes ikut berubah/terhapus: test_closing_browser_stops_server_and_controller, test_stopping_server_closes_browser |
| K2-3 | `src/mica/webui/app.py:197, 218-221` | `EdgeBrowser(settings.ui.fullscreen, camera_preview=...)`, menangkap `EdgeMissing` | K2 | ganti: peluncur browser bawaan | sedang. Tes: test_run_passes_camera_preview_to_browser ikut berubah |
| K2-4 | `src/mica/webui/app.py:9-10, 37, 333` | dokstring "Edge ditutup -> ...", `WATCH_INTERVAL_S`, `--no-browser` "jangan luncurkan Edge" | K2 | ganti teks; hapus `WATCH_INTERVAL_S`; `--no-browser` biarkan (sudah setara mode server saja) | rendah |
| K2-5 | `src/mica/config.py:281` | `fullscreen: bool` di `UiConfig` | K2 | hapus field `ui.fullscreen` | sedang: mengubah config_hash (temuan 4). Tes: parameter `("ui", "fullscreen", "ya")` di tests/unit/test_config.py:125 ikut dihapus |
| K2-6 | `config/dev.yaml:94`, `config/kiosk.yaml:93` | `fullscreen: true` | K2 | hapus | rendah (bersama K2-5) |
| K2-7 | `src/mica/check.py:7, 130-137, 206, 228-231` | baris cek "Microsoft Edge" (`msedge.exe` dicari bila `ui.backend: web`), parameter `edge_paths` | K2 | hapus baris cek Edge; `check` tidak lagi mensyaratkan Edge | rendah. Tes ikut terhapus: test_check_web_backend_without_edge_fails, test_check_web_backend_with_edge_ok (tests/unit/test_setup_check.py:238, 248) |
| K2-8 | `src/mica/eval/resources.py:7, 29, 60-65, 225-234` | kelompok proses "edge" dari `EdgeBrowser.pid` | K2 | biarkan dulu (perekam E-09); putuskan bersama protokol E-09 | tinggi bagi E-09 (temuan 6); 4 baris tes di test_resources.py terkait |
| K2-9 | `src/mica/eval/preview_meter.py:11, 41, 484`; `src/mica/eval/latency.py:21, 178` | kelompok "edge" di pengukur pratinjau dan latensi | K2 | biarkan dulu, ikut keputusan E-09 | sedang; tes di test_eval_latency.py (8 baris) terkait |
| K2-10 | `src/mica/webui/guided.py:127`; `src/mica/webui/answer_format.py:4` | komentar "Edge, server, pekerja ditutup"; "uji kesetaraan lewat Edge" | K2 | ganti teks (guided); answer_format biarkan bila uji kesetaraan Edge headless dipertahankan | rendah |
| K2-11 | `tests/unit/test_answer_format.py:24, 293-300` | `test_js_formatter_matches_python` menjalankan Edge headless (dilewati bila tidak ada) | K2 | biarkan (alat dev, bukan peluncur) | rendah, asal `find_edge` dipertahankan |
| K2-12 | `scripts/ui_bench.py` (44 baris terkait Edge), `scripts/ui_ab_bench.py`, `scripts/ui_preview_bench.py`, `scripts/ui_preview_opt.py` (20) | bench ADR-19 dan pratinjau memakai `EdgeBrowser`/`--edge-extra`/CDP | K2 | biarkan sebagai arsip pengukuran (lihat K5), atau hapus bila pemilik setuju | sedang: skrip rusak setelah K2-1. Tes terkait: tests/unit/test_ui_preview_opt.py, sebagian test_webui.py (memuat scripts/ui_contrast.py, bukan ui_bench) |
| K2-13 | `scripts/startup_profile.py:10-13, 53, 133`; `scripts/l40_startup.ps1:4-5` | profil waktu mulai menutup jendela Edge untuk menghentikan aplikasi; tahap `edge_launched` | K2 | ganti cara berhenti setelah K2-2; tahap diganti nama `browser_opened` | sedang: tests/unit/test_startup_profile.py ikut berubah; nama tahap di log startup lama berbeda |
| K2-14 | `scripts/cpu_threads_bench.py:7, 146, 233` | `EdgeBrowser(s.ui.fullscreen, ...)` | K2 | ganti atau arsipkan (bench sudah selesai, docs/CPU-THREADS.md) | sedang; tests/unit/test_cpu_threads_bench.py terkait |
| K2-15 | `scripts/ui_screens.py:1, 39, 263` | tangkapan layar lewat Edge headless + CDP | K2 | biarkan (alat dev; tidak dipakai saat aplikasi berjalan) | rendah |
| K2-16 | `README.md:13, 69`; `docs/KIOSK.md` (seluruhnya); `docs/PERINTAH.md` | "UI kiosk berjalan di Edge mode kiosk", "Alt+F4 di jendela Edge" | K2 | ganti teks: browser bawaan, jendela biasa | rendah |

## K3. PySide6 / `ui.backend: pyside6`

| No | Lokasi (file:baris) | Isi sekarang | Kategori | Usulan (ganti nama / hapus / biarkan) | Risiko |
|---|---|---|---|---|---|
| K3-1 | `src/mica/ui/main_window.py:1-270` | `MainWindow` PySide6 (QtWidgets), `format_debug` | K3 | hapus | sedang: hilangnya tes kesetaraan (temuan 8). Tes ikut terhapus: seluruh tests/unit/test_ui_window.py (14 tes) |
| K3-2 | `src/mica/ui/app.py:1-132` | `KioskApp`, `build`, `apply_ui_settings`, `python -m mica.ui` (QApplication, QTimer) | K3 | hapus | rendah. Tes ikut terhapus: seluruh tests/integration/test_ui_controller.py (3 tes) |
| K3-3 | `src/mica/ui/__main__.py:1-8` | entry `python -m mica.ui` | K3 | hapus | rendah |
| K3-4 | `src/mica/ui/viewmodel.py:1-112` | ViewModel tanpa Qt | K3 | **biarkan isinya, pindah modul** (misalnya `mica.core.viewmodel`); dipakai webui dan eval/tahap1.py | sedang: impor di src/mica/webui/server.py:47, state.py:30, eval/tahap1.py:53 dan 7 berkas tes; tidak ada tes yang terhapus |
| K3-5 | `src/mica/ui/devfakes.py:1-99` | `FakeWorkerBus`, `FakePipeline`, `FAKE_CAMERA_VALUES` (tanpa Qt) | K3 | **biarkan isinya, pindah modul** (misalnya `mica.core.devfakes`) | sedang: impor di webui/app.py:69,115, scripts/camera_rate.py:73, trial.py (dokstring), dan tes: test_livepreview, test_startup, test_startup_ui, test_trial |
| K3-6 | `src/mica/__main__.py:6-9, 26-36, 48-56, 119-121` | `_launch_pyside6`, `LAUNCHERS` per `ui.backend`, penolakan `--record-resources` untuk non-web | K3 | hapus `_launch_pyside6` dan `LAUNCHERS`; panggil peluncur web langsung | rendah. Tes ikut berubah: test_main_launches_ui_by_backend (parametrize pyside6/web) di test_setup_check.py:305; bagian pyside6 di test_main_recorder_flags (test_resources.py:144-147) |
| K3-7 | `src/mica/config.py:278-280` | `backend: Literal["pyside6", "web"]` + komentar ADR-19 | K3 | hapus field `ui.backend` (ADR-19 final = web) | sedang: config_hash berubah; SDD menyebut `ui.backend` 5 kali. Tes ikut terhapus: test_ui_backend_web_default_and_pyside6_accepted (test_config.py:74-89) dan parameter `("ui", "backend", "qt")` (test_config.py:126) |
| K3-8 | `config/dev.yaml:93`, `config/kiosk.yaml:92` | `backend: web  # ADR-19: web \| pyside6 ...` | K3 | hapus | rendah |
| K3-9 | `src/mica/check.py:228` | `if settings.ui.backend == "web":` | K3 | hapus kondisi (bersama K2-7) | rendah. Tes ikut terhapus: test_check_pyside6_backend_has_no_edge_row (test_setup_check.py:260) |
| K3-10 | `src/mica/webui/state.py:3-5, 205` | "aturan sama dengan mica.ui.main_window (PySide6)", `format_debug` = salinan versi Qt | K3 | biarkan kode; ganti dokstring (salinan menjadi satu-satunya versi) | rendah |
| K3-11 | `src/mica/webui/server.py:4-5, 53`; `src/mica/webui/app.py:1, 6`; `src/mica/core/controller.py:1, 25-26` | komentar "sama dengan PySide6", "setara QTimer", "tanpa Qt" | K3 | ganti teks | rendah |
| K3-12 | `tests/unit/test_webui.py:16, 32-33, 91-209` | tes kesetaraan web vs PySide6 (`qtbot`, `MainWindow`) | K3 | hapus 7 tes: test_view_json_matches_pyside6_render, test_format_debug_same_as_pyside6, test_typing_same_event, test_typing_blocked_while_thinking_in_both, test_topic_same_event, test_talk_and_stop_same_event, test_resend_edited_transcript_same_event; pertimbangkan menulis ulang sebagai tes web murni | sedang (temuan 8) |
| K3-13 | `tests/unit/test_ui_window.py:1-183` | 14 tes MainWindow (pytest-qt) | K3 | hapus berkas | rendah |
| K3-14 | `tests/integration/test_ui_controller.py:1-83` | 3 tes integrasi Qt | K3 | hapus berkas | rendah; alur yang sama sudah diuji tanpa Qt di tests/integration/test_controller.py |
| K3-15 | `tests/conftest.py:5-7` | `QT_QPA_PLATFORM=offscreen` | K3 | hapus | rendah |
| K3-16 | `tests/unit/test_viewmodel.py:94-95`; `tests/integration/test_controller.py:274`; `tests/unit/test_webui.py:742` | cek "PySide6 tidak dimuat" | K3 | biarkan atau sederhanakan (tetap benar setelah dihapus) | rendah |
| K3-17 | `pyproject.toml:31-33` | `PySide6-Essentials==6.12.0` | K3 | hapus dependensi | rendah |
| K3-18 | `pyproject.toml:46` | `pytest-qt==4.5.0` (dev) | K3 | hapus | rendah: semua tes `qtbot` harus sudah dihapus |
| K3-19 | `requirements.lock:64, 67, 83` | `PySide6_Essentials`, `pytest-qt`, `shiboken6` | K3 | hapus, lalu buat ulang lock | rendah; lingkungan tag tahap1-beku tetap memakai lock lama |
| K3-20 | `scripts/ui_bench.py:1-20, 157-175, 646-675, 837-923` | `child_pyside6`, `--ui both\|pyside6\|web` | K3 | hapus cabang pyside6, atau arsipkan skrip (K5) | rendah |
| K3-21 | `README.md:106`; `docs/PERINTAH.md:32`; `docs/KIOSK.md:72` | "UI PySide6 (cadangan, dibekukan)", `python -m mica.ui` | K3 | hapus baris | rendah |
| K3-22 | `docs/UI-WEB.md`, `docs/E-09.md:83` | protokol ADR-19 web vs PySide6 | K3 | biarkan (pra-registrasi/catatan eksperimen) | mengubahnya berarti mengubah catatan sejarah |

## K4. Kode mati

Grep (kata utuh) atas semua definisi tingkat atas di src/mica (kecuali vision/) dan atas impor modul.

| No | Lokasi (file:baris) | Isi sekarang | Kategori | Usulan (ganti nama / hapus / biarkan) | Risiko |
|---|---|---|---|---|---|
| K4-1 | `src/mica/core/session.py:564` | `transitions_markdown` tidak dipanggil di src/; dipakai scripts/session_table.py:11,21 dan tests/unit/test_session.py:480 | K4 | biarkan (alat skrip yang terdokumentasi di docs/PERINTAH.md:102) | - |
| K4-2 | `src/mica/webui/answer_format.py:118` | `format_answer` tidak dipanggil di src/; versi acuan Python untuk static/answer_format.js, dipakai test_answer_format.py dan test_prompt_v3.py:42 | K4 | biarkan (sengaja: acuan uji kesetaraan) | - |
| K4-3 | `src/mica/ui/main_window.py`, `src/mica/ui/app.py` | hanya dipakai oleh `_launch_pyside6`, tes Qt, dan scripts/ui_bench.py | K4 | hapus bersama K3 | lihat K3-1, K3-2 |
| K4-4 | `src/mica/webui/browser.py` (`keep_rendering`, `RENDERING_SWITCHES`) | parameter `keep_rendering=False` hanya dipakai scripts/ui_bench.py dan 1 tes | K4 | hapus bersama K2-1 | lihat K2-1 |
| K4-5 | `src/mica/config.py:282` (`ui.font_scale`) | masih dipakai webui/state.py:136 dan static/app.js:55; **bukan kode mati** walau terkait Qt di ui/app.py | K4 | biarkan | - |
| K4-6 | modul `mica.ask`, `mica.logs` | tidak diimpor di src/, tetapi entry point CLI (`python -m mica.ask`, `python -m mica.logs export`) yang terdokumentasi di docs/PERINTAH.md:44, 89 | K4 | biarkan | - |

Flag CLI: semua flag di `python -m mica`, `python -m mica.webui`, `setup`, dan `check` dibaca oleh kodenya.
Tidak ada flag yang terdefinisi tetapi tidak dipakai. `python -m mica.ui` (3 flag) ikut terhapus di K3-3.

## K5. File yang tampak usang (hanya ditandai)

| No | Lokasi (file:baris) | Isi sekarang | Kategori | Usulan (ganti nama / hapus / biarkan) | Risiko |
|---|---|---|---|---|---|
| K5-1 | `docs/KIOSK.md` | panduan pasang laptop kiosk (Edge layar penuh, PySide6 cadangan) | K5 | ganti nama -> docs/PEMASANGAN.md, tulis ulang | tautan di README.md:8 |
| K5-2 | `config/kiosk.yaml` | config produksi | K5 | ganti nama -> config/prod.yaml | path default di check.py:24; banyak dokumen merujuk |
| K5-3 | `docs/ui-screens/README.md` | "Tangkapan layar UI kiosk" | K5 | ganti judul; tangkapan layar biarkan | rendah |
| K5-4 | `scripts/ui_bench.py`, `scripts/ui_ab_bench.py`, `scripts/ui_preview_bench.py`, `scripts/ui_preview_opt.py` | bench ADR-19 dan pratinjau yang sudah selesai (Langkah 29-38) | K5 | tandai arsip; pertahankan selama hasilnya dirujuk di skripsi | tests/unit/test_ui_preview_opt.py dan bagian test_webui.py ikut terdampak bila dihapus |
| K5-5 | `scripts/e05_smoke_synthetic.py` | uji asap STT tanpa mikrofon, sekali pakai (Langkah E-05) | K5 | tandai; tidak ada tes | rendah |
| K5-6 | `scripts/l40_startup.ps1` | profil waktu mulai Langkah 40 (Edge kiosk) | K5 | tandai; rusak setelah K2 | rendah |
| K5-7 | `scripts/cpu_threads_bench.py` | bench thread yang sudah diputuskan (docs/CPU-THREADS.md) | K5 | tandai arsip | tests/unit/test_cpu_threads_bench.py |
| K5-8 | `ui-baru-versi-f/` (di-.gitignore) | sumber desain versi F, sudah disalin ke webui/static (komentar .gitignore Langkah 57) | K5 | tandai; tidak dilacak git | - |
| K5-9 | `results/ADR-19/*/static-*` (dilacak git) | salinan file statis lama untuk A/B | K5 | biarkan (hasil run, di luar cakupan) | - |
| K5-10 | `docs/PROMPT-V3.md`, `docs/PROMPT-V4.md` | pra-reg prompt lama (sekarang v5) | K5 | biarkan (catatan eksperimen) | - |
| K5-11 | `docs/UI-WEB.md`, `docs/UI-PREVIEW-OPT.md` | protokol ADR-19 dan optimasi pratinjau | K5 | biarkan (catatan eksperimen) | - |
| K5-12 | `README.md:3, 8, 13, 63-69, 82, 95-97, 104-106, 114` | deskripsi kiosk, Edge, PySide6 | K5 | tulis ulang bagian terkait | rendah |
| K5-13 | `pyproject.toml:8` | `description = "MICA: kiosk informasi PMB ..."` | K5 | ganti teks | rendah |

## C. Rencana verifikasi perilaku RAG (belum dijalankan)

**Perintah persis yang diminta belum ada.** Belum ada perintah yang menjalankan retrieval saja atas
beberapa soal dari `uji-tahap1-129.csv` lalu mencetak ID chunk dan skornya.

- `python -m mica.eval retrieval` butuh dataset JSONL dengan kunci relevansi (E-01), bukan CSV Tahap 1.
- `python -m mica.rag search "<pertanyaan>" --config <yaml> [--retriever ...] [--k 5]` paling mendekati:
  tanpa LLM, tanpa Groq, satu pertanyaan per panggilan. Keluarannya skor (6 desimal), `ranks`, `doc_id`, dan
  `section`, tetapi **bukan `chunk_id`**. Perintah ini juga tidak menjalankan `scrub_pii` lebih dulu seperti
  pipeline.
- `data/eval/official/runs/tahap1/answers.jsonl` menyimpan `top5[].chunk_id` per soal sebagai acuan ketiga,
  tetapi tanpa skor per chunk (hanya `dense_at_1`).

Cara yang bisa dipakai tanpa membuat perintah baru:

```bash
# dari D:\SKRIPSI\mica, di folder kerja yang sama (data/kb/ dan models/ di-.gitignore, jadi tidak ada di worktree baru)
python -c "import csv;[print(r['pertanyaan']) for r in list(csv.DictReader(open('data/eval/official/uji-tahap1-129.csv',encoding='utf-8'),delimiter=';'))[:5]]" > ../verif-q.txt
for ref in tahap1-beku refactor/webapp; do
  git checkout -q "$ref"
  while IFS= read -r q; do
    python -m mica.rag search "$q" --config config/dev.yaml --retriever hybrid --k 5
  done < ../verif-q.txt | grep -E '^[0-9]+\. skor' > "../verif-${ref//\//_}.txt"
done
git checkout -q refactor/webapp
diff ../verif-tahap1-beku.txt ../verif-refactor_webapp.txt && echo "retrieval sama"
```

- Baris yang dibandingkan berisi peringkat, skor, `ranks`, `doc_id`, dan `section`. Pratinjau teks dan lama
  pencarian sengaja dibuang dengan `grep`, karena lama pencarian selalu berbeda.
- Syarat: `config/dev.yaml` tetap ada dengan nama yang sama di kedua ref dan masih menunjuk
  `kb.active_id: official-2026-10-24-v5`. Bila dev.yaml ikut diganti nama, sesuaikan `--config` per ref.
- Hasil yang diharapkan: `diff` kosong.
- `config_hash` tidak dipakai sebagai bukti karena pasti berubah (temuan 4).
- Kekurangan: tanpa `chunk_id`, dua chunk dengan `doc_id` dan `section` sama tidak bisa dibedakan.
  Bila perlu bukti per `chunk_id`, perintah kecil baru harus dibuat dulu, dan itu menunggu keputusan pemilik.

## K1. Kata "kiosk" (semua baris dalam cakupan)

| No | Lokasi (file:baris) | Isi sekarang | Kategori | Usulan (ganti nama / hapus / biarkan) | Risiko |
|---|---|---|---|---|---|
| K1-1 | `src/mica/__main__.py:1` | """Entry point kiosk. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-2 | `src/mica/__main__.py:3` | python -m mica [--config config/kiosk.yaml] [--fake-workers] [--fake-pipeline] | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-3 | `src/mica/__main__.py:6` | Bila OK: proses vision + suara (start_workers), KioskController, dan UI sesuai ui.backend: | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-4 | `src/mica/__main__.py:7` | web (mica.webui.app: server Flask + Edge kiosk, UI utama) atau pyside6 (mica.ui.app, cadangan). | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-5 | `src/mica/__main__.py:32` | kiosk = build(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline) | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-6 | `src/mica/__main__.py:33` | apply_ui_settings(app, kiosk.window, settings)  # type: ignore[arg-type] | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-7 | `src/mica/__main__.py:34` | kiosk.timer.start() | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-8 | `src/mica/__main__.py:98` | if args.trial_values:  # Langkah 41: setelah check, di memori; kiosk ditolak | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-9 | `src/mica/ask.py:1` | """CLI uji cepat M-06 (mode dev): satu pertanyaan lewat AnswerPipeline yang sama dengan kiosk. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-10 | `src/mica/audio/worker.py:185` | "factory audio palsu hanya boleh saat app.mode: dev (ditolak di kiosk)" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-11 | `src/mica/check.py:1` | """python -m mica check: pemeriksaan sebelum kiosk dinyalakan, untuk staf. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-12 | `src/mica/check.py:4` | config (M-01; di kiosk semua null wajib terisi), file model dan sha256, KB aktif dan | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-13 | `src/mica/check.py:22` | from mica.config import ConfigError, Settings, load_settings, missing_kiosk_fields | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-14 | `src/mica/check.py:24` | DEFAULT_CONFIG = Path("config/kiosk.yaml") | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-15 | `src/mica/check.py:53` | missing = missing_kiosk_fields(settings) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-16 | `src/mica/check.py:54` | return CheckRow("config", "GAGAL", f"mode kiosk: {len(missing)} kunci belum diisi: " | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-17 | `src/mica/check.py:115` | f"{message}; {lack} tidak ditemukan, kiosk tetap bisa dipakai lewat teks")  # fmt: skip | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-18 | `src/mica/check.py:248` | verdict = "ADA GAGAL: perbaiki baris GAGAL sebelum menjalankan kiosk" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-19 | `src/mica/check.py:250` | verdict = "SIAP DENGAN PERINGATAN: kiosk bisa dijalankan (python -m mica); baca PERINGATAN" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-20 | `src/mica/check.py:252` | verdict = "SEMUA OK: kiosk siap dijalankan (python -m mica)" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-21 | `src/mica/config.py:29` | CFG_GEMINI_IN_KIOSK = ErrorCode.CFG_GEMINI_IN_KIOSK | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-22 | `src/mica/config.py:48` | mode: Literal["kiosk", "dev"] | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-23 | `src/mica/config.py:54` | # hash commit Hugging Face lengkap (N-14); wajib di kiosk, null di dev = revisi main | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-24 | `src/mica/config.py:69` | # hash commit Hugging Face lengkap (N-14); wajib di kiosk, null di dev = revisi main | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-25 | `src/mica/config.py:153` | # ID model Groq Whisper (SDD 13.1, bagian 12); dipilih di E-05, wajib di kiosk hanya bila | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-26 | `src/mica/config.py:166` | # null = bawaan file .onnx.json suara (inference.length_scale); boleh null di kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-27 | `src/mica/config.py:278` | # ADR-19: web = Flask + Edge kiosk, UI utama (keputusan pemilik proyek 17 Okt 2026); | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-28 | `src/mica/config.py:361` | if self.app.mode == "kiosk" and self.ui.camera_preview == "debug": | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-29 | `src/mica/config.py:364` | "kiosk memakai public atau off" | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-30 | `src/mica/config.py:404` | def _check_gemini_in_kiosk(raw: dict[str, Any]) -> None: | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-31 | `src/mica/config.py:407` | if not isinstance(app, dict) or app.get("mode") != "kiosk" or not isinstance(llm, dict): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-32 | `src/mica/config.py:415` | CFG_GEMINI_IN_KIOSK, | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-33 | `src/mica/config.py:428` | def _optional_in_kiosk(settings: Settings) -> set[str]: | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-34 | `src/mica/config.py:456` | def _missing_kiosk_fields(settings: Settings) -> list[str]: | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-35 | `src/mica/config.py:459` | optional = _optional_in_kiosk(settings) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-36 | `src/mica/config.py:478` | def missing_kiosk_fields(settings: Settings) -> list[str]: | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-37 | `src/mica/config.py:479` | """Kunci yang masih null/placeholder dan wajib diisi di mode kiosk (untuk python -m mica check).""" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-38 | `src/mica/config.py:480` | return _missing_kiosk_fields(settings) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-39 | `src/mica/config.py:486` | """require_complete False: lewati cek null mode kiosk (hanya untuk check, yang melaporkan | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-40 | `src/mica/config.py:487` | daftar kuncinya sendiri lewat missing_kiosk_fields).""" | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-41 | `src/mica/config.py:506` | _check_gemini_in_kiosk(raw) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-42 | `src/mica/config.py:516` | if settings.app.mode == "kiosk" and require_complete: | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-43 | `src/mica/config.py:517` | missing = _missing_kiosk_fields(settings) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-44 | `src/mica/config.py:521` | "mode kiosk: field berikut belum diisi\n  " + "\n  ".join(missing), | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-45 | `src/mica/core/bus.py:114` | # pratinjau UI kiosk: antrean TERPISAH dari bus event (maxsize 1, frame lama dibuang); | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-46 | `src/mica/core/controller.py:1` | """KioskController tanpa Qt: memompa bus, meneruskan event ke M-09, mengeksekusi Action (SDD 3.3, | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-47 | `src/mica/core/controller.py:144` | class KioskController: | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-48 | `src/mica/core/controller.py:306` | except Exception as exc:  # noqa: BLE001 - pipeline tidak boleh mematikan kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-49 | `src/mica/core/types.py:33` | CFG_GEMINI_IN_KIOSK = "CFG_GEMINI_IN_KIOSK" | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-50 | `src/mica/eval/__main__.py:194` | lat.add_argument("--label", required=True, help="nama run, mis. kiosk-fps2-t1") | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-51 | `src/mica/eval/__main__.py:406` | f"eval {command} hanya boleh saat app.mode: dev (frame relawan ditolak di mode kiosk)" | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-52 | `src/mica/eval/__main__.py:490` | f"model {args.model} tanpa keypoint: kiosk wajib model -pose (amandemen 1 E-07); " | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-53 | `src/mica/eval/__main__.py:873` | raise SttEvalError("eval stt hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-54 | `src/mica/eval/preview_meter.py:50` | raise MeasureRefused("--measure-preview hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-55 | `src/mica/eval/resources.py:41` | "--record-resources hanya untuk app.mode: dev; di kiosk hanya untuk E-09 dengan --e09" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-56 | `src/mica/eval/resources.py:173` | except Exception:  # noqa: BLE001, S110 - perekam tidak boleh mematikan kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-57 | `src/mica/eval/resources.py:222` | help="izinkan perekam di app.mode kiosk untuk E-09 (dicatat di run.json)")  # fmt: skip | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-58 | `src/mica/eval/stt.py:50` | # SDD 2.4 (aturan E-05): p95 waktu sampai transkripsi tampil paling lama 3 detik di laptop kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-59 | `src/mica/eval/stt.py:55` | "3 detik di laptop kiosk; pemenang WER terkecil; seri dimenangkan STT lokal." | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-60 | `src/mica/eval/stt.py:362` | "kiosk (SDD 2.4).")  # fmt: skip | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-61 | `src/mica/eval/vision.py:34` | USED_MODEL = "yolo26n-pose"  # amandemen 1 E-07: kiosk wajib model dengan keypoint | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-62 | `src/mica/rag/background.py:53` | except Exception as exc:  # noqa: BLE001 - kiosk tetap jalan, jawaban = penolakan baku | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-63 | `src/mica/rag/followup.py:37` | "sebelumnya dan pertanyaan baru dari pengunjung kiosk. Bila pertanyaan baru adalah lanjutan " | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-64 | `src/mica/rag/llm.py:29` | from mica.config import API_KEY_VARS, CFG_GEMINI_IN_KIOSK, CFG_INVALID, ConfigError, Settings | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-65 | `src/mica/rag/llm.py:385` | """Khusus mode dev; ditolak di mode kiosk (N-09, SDD 8.2). | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-66 | `src/mica/rag/llm.py:397` | mode: Literal["kiosk", "dev"], | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-67 | `src/mica/rag/llm.py:404` | raise ConfigError(CFG_GEMINI_IN_KIOSK, "GeminiProvider hanya boleh saat app.mode: dev") | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-68 | `src/mica/setup.py:1` | """python -m mica setup: unduh semua model kiosk dengan revisi/sha256 terkunci (N-14). | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-69 | `src/mica/setup.py:7` | Berbeda dari fetch-* (dev saja), setup boleh dijalankan dengan config kiosk karena dipakai | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-70 | `src/mica/setup.py:8` | saat pemasangan, sebelum kiosk berjalan; kiosk sendiri tidak pernah mengunduh. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-71 | `src/mica/setup.py:24` | DEFAULT_CONFIG = Path("config/kiosk.yaml") | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-72 | `src/mica/trial.py:4` | di memori; file config tidak diubah. Hanya boleh saat app.mode: dev; config kiosk ditolak | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-73 | `src/mica/trial.py:5` | (config kiosk baru diisi dari hasil eksperimen, SDD bagian 12). Saat aktif, daftar kunci dan | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-74 | `src/mica/trial.py:65` | "config kiosk diisi dari hasil eksperimen, bukan nilai coba", | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-75 | `src/mica/ui/app.py:1` | """M-10 aplikasi: QApplication + MainWindow + KioskController (SDD M-10, 3.3). | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-76 | `src/mica/ui/app.py:7` | --fake-pipeline: jawaban palsu tanpa Groq. Keduanya ditolak di mode kiosk. | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-77 | `src/mica/ui/app.py:26` | from mica.core.controller import KioskController | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-78 | `src/mica/ui/app.py:40` | class KioskApp: | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-79 | `src/mica/ui/app.py:42` | controller: KioskController | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-80 | `src/mica/ui/app.py:54` | ) -> KioskApp: | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-81 | `src/mica/ui/app.py:58` | raise UiError("pekerja/pipeline palsu hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-82 | `src/mica/ui/app.py:85` | controller = KioskController(bus, Session.from_settings(settings), pipeline, | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-83 | `src/mica/ui/app.py:94` | return KioskApp(window, controller, timer) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-84 | `src/mica/ui/app.py:126` | kiosk = build(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-85 | `src/mica/ui/app.py:130` | apply_ui_settings(app, kiosk.window, settings)  # type: ignore[arg-type] | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-86 | `src/mica/ui/app.py:131` | kiosk.timer.start() | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-87 | `src/mica/ui/devfakes.py:8` | memanggil Groq. Keduanya ditolak di mode kiosk oleh mica.ui.app. | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-88 | `src/mica/ui/main_window.py:4` | memancarkannya lewat sinyal event_emitted; KioskController yang memprosesnya. Panel debug | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-89 | `src/mica/webui/app.py:1` | """UI web (ADR-19, opsi ui.backend: web): rakit KioskController + server Flask + Edge, tanpa Qt. | K1+K2 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-90 | `src/mica/webui/app.py:14` | pekerja kamera asli (boleh dengan --fake-camera), ditolak di kiosk dan dengan --fake-workers. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-91 | `src/mica/webui/app.py:31` | from mica.core.controller import KioskController | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-92 | `src/mica/webui/app.py:56` | ) -> KioskController: | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-93 | `src/mica/webui/app.py:60` | raise WebUiError("pekerja/pipeline palsu hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-94 | `src/mica/webui/app.py:96` | controller = KioskController(bus, Session.from_settings(settings), pipeline, webui.show_item, | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-95 | `src/mica/webui/app.py:144` | controller: KioskController, | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-96 | `src/mica/webui/app.py:266` | def make_preview_meter(settings: Settings, webui: WebUi, controller: KioskController, | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-97 | `src/mica/webui/app.py:303` | raise WebUiError("--prompt-variant hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-98 | `src/mica/webui/app.py:331` | help="uji coba langsung varian prompt (v2 = paraphrase); dev saja, kiosk ditolak", | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-99 | `src/mica/webui/browser.py:3` | Flag (Microsoft Learn, "Configure Microsoft Edge kiosk mode", ms.date 14 Okt 2025, bukti [53]; | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-100 | `src/mica/webui/browser.py:4` | dicek 17 Okt 2026): --kiosk <url> --edge-kiosk-type=fullscreen (Digital/Interactive signage, | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-101 | `src/mica/webui/browser.py:64` | # limit to the number of renderer processes". Nilai 1: kiosk hanya punya satu halaman. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-102 | `src/mica/webui/browser.py:98` | return [*cmd, "--kiosk", url, "--edge-kiosk-type=fullscreen"] | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-103 | `src/mica/webui/guided.py:1` | """Uji terpandu (--guided-test, dev saja): kotak petunjuk kecil di halaman kiosk berisi langkah | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-104 | `src/mica/webui/guided.py:25` | raise GuidedRefused("--guided-test hanya boleh saat app.mode: dev (ditolak di kiosk)") | K1 | ganti kata: kiosk -> prod / aplikasi | pesan galat; tes yang mencocokkan teks pesan ikut diganti |
| K1-105 | `src/mica/webui/guided.py:39` | Phase("disapa", 45, 90, "Berdiri di depan kiosk dan tunggu sampai MICA menyapa."), | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-106 | `src/mica/webui/server.py:4` | - KioskController dan ViewModel yang sama dengan PySide6; web hanya merender ViewModel. | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-107 | `src/mica/webui/server.py:52` | HOST = "127.0.0.1"  # tidak pernah 0.0.0.0: UI hanya untuk laptop kiosk itu sendiri | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-108 | `src/mica/webui/static/app.js:1` | // UI kiosk MICA (Langkah 37c): merender JSON ViewModel dari server dan mengirim event input. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-109 | `src/mica/webui/static/style.css:1` | /* Tata letak UI kiosk MICA, versi F (21 Okt 2026): mengikuti gambar acuan hasa lalu dirapikan. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-110 | `config/dev.yaml:2` | mode: dev                   # kiosk \| dev; Gemini hanya boleh di dev | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-111 | `config/dev.yaml:25` | revision: null                  # N-14; hash commit lengkap, wajib di kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-112 | `config/dev.yaml:106` | camera_preview: debug             # off \| public \| debug (debug ditolak di kiosk); Langkah 37 | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-113 | `config/kiosk.yaml:2` | mode: kiosk                 # kiosk \| dev; Gemini hanya boleh di dev | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-114 | `config/kiosk.yaml:10` | # active_id: dev-2026-10-15-v2  # arsip, dipakai E-01..E-04 (KB dev tidak dipakai di kiosk) | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-115 | `config/kiosk.yaml:16` | revision: null                  # N-14; hash commit lengkap, wajib di kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-116 | `config/kiosk.yaml:25` | revision: null                  # N-14; hash commit lengkap, wajib di kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-117 | `config/kiosk.yaml:105` | camera_preview: public            # off \| public \| debug (debug ditolak di kiosk); Langkah 37 | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-118 | `tests/integration/test_controller.py:1` | """KioskController ujung ke ujung: bus palsu di dalam proses, pipeline palsu, jam palsu. | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-119 | `tests/integration/test_controller.py:25` | from mica.core.controller import KioskController | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-120 | `tests/integration/test_controller.py:105` | self.ctrl = KioskController( | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-121 | `tests/integration/test_turn_timings.py:14` | from mica.core.controller import TURN_TIMING_KEYS, KioskController | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-122 | `tests/integration/test_turn_timings.py:72` | self.ctrl = KioskController(self.bus, self.session, pipeline or RunPipeline(), | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-123 | `tests/integration/test_ui_controller.py:1` | """M-10 + KioskController lewat QTimer (offscreen): alur ketik lengkap sampai jawaban dan sumber. | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-124 | `tests/integration/test_ui_controller.py:44` | kiosk = build(_settings(tmp_path), bus=bus, pipeline=pipeline) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-125 | `tests/integration/test_ui_controller.py:45` | w = kiosk.window | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-126 | `tests/integration/test_ui_controller.py:47` | kiosk.timer.start() | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-127 | `tests/integration/test_ui_controller.py:60` | qtbot.waitUntil(lambda: kiosk.controller.session.state == VisitState.READY, timeout=3000) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-128 | `tests/integration/test_ui_controller.py:64` | assert bus.stopped and not kiosk.timer.isActive() | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-129 | `tests/integration/test_ui_controller.py:68` | kiosk = build(_settings(tmp_path), fake_workers=True, fake_pipeline=True) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-130 | `tests/integration/test_ui_controller.py:69` | qtbot.addWidget(kiosk.window) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-131 | `tests/integration/test_ui_controller.py:70` | kiosk.timer.start() | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-132 | `tests/integration/test_ui_controller.py:71` | kiosk.window.event_emitted.emit(TextSubmitted("Akreditasi apa?")) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-133 | `tests/integration/test_ui_controller.py:73` | for m in kiosk.window.vm.messages), timeout=5000)  # fmt: skip | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-134 | `tests/integration/test_ui_controller.py:74` | assert isinstance(kiosk.controller.pipeline, FakePipeline) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-135 | `tests/integration/test_ui_controller.py:75` | kiosk.window.close() | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-136 | `tests/integration/test_ui_controller.py:78` | def test_fakes_refused_in_kiosk(tmp_path): | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-137 | `tests/integration/test_ui_controller.py:79` | settings = _settings(tmp_path, mode="kiosk") | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-138 | `tests/integration/test_ui_controller.py:80` | with pytest.raises(UiError, match="kiosk"): | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-139 | `tests/integration/test_ui_controller.py:82` | with pytest.raises(UiError, match="kiosk"): | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-140 | `tests/unit/test_annotation_v4_sheet.py:69` | for name in ("dev.yaml", "kiosk.yaml"):  # keputusan menunggu penilai manusia | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-141 | `tests/unit/test_audio_worker.py:172` | def test_worker_config_rejects_fakes_and_diagnose_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-142 | `tests/unit/test_audio_worker.py:173` | with pytest.raises(AudioWorkerConfigError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-143 | `tests/unit/test_audio_worker.py:174` | AudioWorkerConfig.from_settings(_settings("kiosk"), VALUES, **FAKES) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-144 | `tests/unit/test_audio_worker.py:176` | AudioWorkerConfig.from_settings(_settings("kiosk"), VALUES, diagnose=True) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-145 | `tests/unit/test_audio_worker.py:419` | def test_bus_demo_refused_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-146 | `tests/unit/test_audio_worker.py:422` | cli.cmd_bus_demo(args, _settings("kiosk")) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-147 | `tests/unit/test_bus.py:65` | def test_fake_factory_rejected_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-148 | `tests/unit/test_bus.py:66` | with pytest.raises(WorkerConfigError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-149 | `tests/unit/test_bus.py:68` | _settings("kiosk"), TEST_VALUES, camera_factory="tests.fakes:make_fake_camera" | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-150 | `tests/unit/test_bus.py:73` | forged = VisionWorkerConfig(**{**cfg.__dict__, "mode": "kiosk"}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-151 | `tests/unit/test_bus.py:74` | with pytest.raises(WorkerConfigError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-152 | `tests/unit/test_bus.py:85` | start_workers(_settings("kiosk"), cfg) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-153 | `tests/unit/test_config.py:8` | CFG_GEMINI_IN_KIOSK, | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-154 | `tests/unit/test_config.py:17` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-155 | `tests/unit/test_config.py:48` | # Isi semua null dengan nilai dummy supaya bisa diuji di mode kiosk. | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-156 | `tests/unit/test_config.py:54` | def _complete_kiosk_raw() -> dict: | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-157 | `tests/unit/test_config.py:56` | raw["app"]["mode"] = "kiosk" | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-158 | `tests/unit/test_config.py:57` | raw["ui"]["camera_preview"] = "public"  # debug ditolak di kiosk | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-159 | `tests/unit/test_config.py:69` | def test_complete_kiosk_config_loads(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-160 | `tests/unit/test_config.py:70` | settings = load_settings(_write(tmp_path, _complete_kiosk_raw())) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-161 | `tests/unit/test_config.py:71` | assert settings.app.mode == "kiosk" | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-162 | `tests/unit/test_config.py:77` | kiosk = yaml.safe_load(KIOSK_YAML.read_text(encoding="utf-8")) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-163 | `tests/unit/test_config.py:78` | assert kiosk["ui"]["backend"] == "web" | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-164 | `tests/unit/test_config.py:149` | def test_gemini_rejected_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-165 | `tests/unit/test_config.py:150` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-166 | `tests/unit/test_config.py:154` | assert exc.value.code == CFG_GEMINI_IN_KIOSK | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-167 | `tests/unit/test_config.py:159` | raw["app"]["mode"] = "kiosk" | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-168 | `tests/unit/test_config.py:164` | assert exc.value.code == CFG_GEMINI_IN_KIOSK | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-169 | `tests/unit/test_config.py:174` | def test_null_rejected_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-170 | `tests/unit/test_config.py:175` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-171 | `tests/unit/test_config.py:185` | def test_placeholder_model_id_rejected_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-172 | `tests/unit/test_config.py:186` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-173 | `tests/unit/test_config.py:194` | def test_current_kiosk_yaml_rejected(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-174 | `tests/unit/test_config.py:196` | load_settings(KIOSK_YAML) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-175 | `tests/unit/test_config.py:272` | def test_current_kiosk_yaml_has_official_active_id(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-176 | `tests/unit/test_config.py:273` | # Langkah 61: kb.active_id kiosk diisi KB resmi; field TBD lain masih membuat kiosk.yaml ditolak | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-177 | `tests/unit/test_config.py:275` | load_settings(KIOSK_YAML) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-178 | `tests/unit/test_config.py:278` | raw = yaml.safe_load(KIOSK_YAML.read_text(encoding="utf-8")) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-179 | `tests/unit/test_config.py:283` | def test_hybrid_params_required_for_hybrid_in_kiosk(tmp_path, field): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-180 | `tests/unit/test_config.py:284` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-181 | `tests/unit/test_config.py:294` | def test_hybrid_params_optional_for_other_retrievers_in_kiosk(tmp_path, retriever): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-182 | `tests/unit/test_config.py:295` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-183 | `tests/unit/test_config.py:305` | def test_stt_threads_required_for_faster_whisper_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-184 | `tests/unit/test_config.py:306` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-185 | `tests/unit/test_config.py:315` | def test_groq_model_required_in_kiosk_only_for_groq_backend(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-186 | `tests/unit/test_config.py:316` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-187 | `tests/unit/test_config.py:326` | def test_groq_model_dev_value_and_kiosk_null(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-188 | `tests/unit/test_config.py:328` | kiosk = load_settings(KIOSK_YAML, require_complete=False) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-189 | `tests/unit/test_config.py:329` | assert kiosk.audio.stt.groq_model is None | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-190 | `tests/unit/test_config.py:332` | def test_stt_threads_optional_for_groq_whisper_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-191 | `tests/unit/test_config.py:333` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-192 | `tests/unit/test_config.py:351` | @pytest.mark.parametrize("path", [DEV_YAML, KIOSK_YAML]) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-193 | `tests/unit/test_config.py:406` | def test_embedder_revision_required_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-194 | `tests/unit/test_config.py:407` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-195 | `tests/unit/test_config.py:431` | def test_reranker_revision_required_in_kiosk_when_enabled(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-196 | `tests/unit/test_config.py:432` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-197 | `tests/unit/test_config.py:440` | def test_reranker_revision_optional_in_kiosk_when_disabled(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-198 | `tests/unit/test_config.py:441` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-199 | `tests/unit/test_config.py:455` | def test_vision_conf_imgsz_required_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-200 | `tests/unit/test_config.py:456` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-201 | `tests/unit/test_config.py:485` | def test_box_upper_required_in_kiosk_when_used(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-202 | `tests/unit/test_config.py:486` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-203 | `tests/unit/test_config.py:494` | def test_box_upper_required_in_kiosk_as_keypoint_fallback(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-204 | `tests/unit/test_config.py:495` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-205 | `tests/unit/test_config.py:503` | def test_keypoint_torso_required_in_kiosk_when_used(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-206 | `tests/unit/test_config.py:504` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-207 | `tests/unit/test_config.py:512` | def test_keypoint_torso_optional_in_kiosk_for_box_upper(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-208 | `tests/unit/test_config.py:513` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-209 | `tests/unit/test_config.py:577` | def test_unused_signal_threshold_optional_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-210 | `tests/unit/test_config.py:578` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-211 | `tests/unit/test_config.py:588` | def test_kiosk_yaml_vision_uses_pose_and_signal_is_tbd(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-212 | `tests/unit/test_config.py:589` | raw = yaml.safe_load(KIOSK_YAML.read_text(encoding="utf-8"))["vision"] | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-213 | `tests/unit/test_config.py:599` | def test_camera_preview_debug_rejected_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-214 | `tests/unit/test_config.py:600` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-215 | `tests/unit/test_config.py:610` | def test_kiosk_yaml_preview_public_with_trial_values(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-216 | `tests/unit/test_config.py:611` | raw = yaml.safe_load(KIOSK_YAML.read_text(encoding="utf-8")) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-217 | `tests/unit/test_config.py:613` | text = KIOSK_YAML.read_text(encoding="utf-8") | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-218 | `tests/unit/test_config.py:618` | @pytest.mark.parametrize(("path", "fps"), [(DEV_YAML, 15), (KIOSK_YAML, 10)]) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-219 | `tests/unit/test_config.py:621` | # dev 15 sejak 21 Okt 2026 (keputusan pengguna); kiosk tetap 10 | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-220 | `tests/unit/test_config.py:628` | if path == DEV_YAML:  # kiosk.yaml masih berisi TBD (null), dimuat lengkap di tes lain | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-221 | `tests/unit/test_cpu_threads.py:37` | kiosk = yaml.safe_load((ROOT / "config/kiosk.yaml").read_text(encoding="utf-8")) | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-222 | `tests/unit/test_cpu_threads.py:38` | assert kiosk["audio"]["tts"]["threads"] is None and kiosk["vision"]["threads"] is None | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-223 | `tests/unit/test_cpu_threads_bench.py:75` | mode = "kiosk" | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-224 | `tests/unit/test_eval_color.py:250` | def test_cli_color_refused_in_kiosk(tmp_path, monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-225 | `tests/unit/test_eval_color.py:254` | kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-226 | `tests/unit/test_eval_color.py:255` | monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-227 | `tests/unit/test_eval_color.py:258` | assert "mode kiosk" in capsys.readouterr().err | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-228 | `tests/unit/test_eval_stt.py:1` | """M-12 eval stt (E-05): manifest, metrik, transkripsi palsu, Recall@5, Groq palsu, kiosk. | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-229 | `tests/unit/test_eval_stt.py:23` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-230 | `tests/unit/test_eval_stt.py:303` | def test_eval_stt_refused_in_kiosk(tmp_path, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-231 | `tests/unit/test_eval_stt.py:305` | code = cli.main(["stt", "--config", str(KIOSK_YAML), "--dataset", str(manifest), *TRIAL]) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-232 | `tests/unit/test_eval_stt.py:308` | assert "app.mode: dev" in err or "mode kiosk" in err | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-233 | `tests/unit/test_eval_stt.py:311` | def test_eval_stt_refused_in_kiosk_even_when_complete(tmp_path, monkeypatch): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-234 | `tests/unit/test_eval_stt.py:315` | kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-235 | `tests/unit/test_eval_stt.py:316` | monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-236 | `tests/unit/test_eval_vision.py:2` | ber-seed, aturan pemilihan, dataset, CLI dengan predictor palsu, dan penolakan mode kiosk.""" | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-237 | `tests/unit/test_eval_vision.py:18` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-238 | `tests/unit/test_eval_vision.py:309` | def test_cli_vision_refused_in_kiosk(tmp_path, monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-239 | `tests/unit/test_eval_vision.py:313` | kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-240 | `tests/unit/test_eval_vision.py:314` | monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-241 | `tests/unit/test_eval_vision.py:315` | code = cli.main(["vision", "--config", str(KIOSK_YAML), "--dataset", str(tmp_path)]) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-242 | `tests/unit/test_eval_vision.py:317` | assert "mode kiosk" in capsys.readouterr().err | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-243 | `tests/unit/test_eval_vision_scenarios.py:225` | def test_cli_vision_scenarios_refused_in_kiosk(tmp_path, monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-244 | `tests/unit/test_eval_vision_scenarios.py:229` | kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-245 | `tests/unit/test_eval_vision_scenarios.py:230` | monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-246 | `tests/unit/test_eval_vision_scenarios.py:234` | assert "mode kiosk" in capsys.readouterr().err | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-247 | `tests/unit/test_guided.py:26` | def _kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-248 | `tests/unit/test_guided.py:28` | return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-249 | `tests/unit/test_guided.py:31` | def test_refused_in_kiosk(capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-250 | `tests/unit/test_guided.py:35` | with pytest.raises(GuidedRefused, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-251 | `tests/unit/test_guided.py:36` | check_allowed("kiosk") | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-252 | `tests/unit/test_guided.py:37` | assert run(_kiosk(), no_browser=True, guided_test=True) == 2 | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-253 | `tests/unit/test_guided.py:38` | assert "kiosk" in capsys.readouterr().err | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-254 | `tests/unit/test_livepreview.py:1` | """Pratinjau kamera UI kiosk (Langkah 37): pixelate public dibandingkan piksel dengan sumber palsu, | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-255 | `tests/unit/test_livepreview.py:3` | debug ditolak di kiosk, laju pratinjau tidak menambah inferensi, dan jalur /preview server.""" | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-256 | `tests/unit/test_livepreview.py:249` | replace(cfg, mode="kiosk").validate() | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-257 | `tests/unit/test_livepreview.py:250` | replace(cfg, mode="kiosk", camera_preview="public").validate() | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-258 | `tests/unit/test_llm.py:10` | from mica.config import CFG_GEMINI_IN_KIOSK, CFG_INVALID, ConfigError, load_settings | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-259 | `tests/unit/test_llm.py:265` | def test_gemini_rejected_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-260 | `tests/unit/test_llm.py:267` | GeminiProvider("gemini-x", mode="kiosk", api_key=SecretStr(KEY)) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-261 | `tests/unit/test_llm.py:268` | assert exc.value.code == CFG_GEMINI_IN_KIOSK | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-262 | `tests/unit/test_pipeline.py:314` | def test_ask_cli_rejects_kiosk_config(tmp_path, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-263 | `tests/unit/test_pipeline.py:317` | assert main(["x", "--config", str(ROOT / "config" / "kiosk.yaml")]) == 2 | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-264 | `tests/unit/test_pipeline.py:380` | # Langkah 55: rag.followup_mode dual dipilih FOLLOWUP.md (dev dan kiosk) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-265 | `tests/unit/test_preview_meter.py:49` | def test_refused_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-266 | `tests/unit/test_preview_meter.py:51` | with pytest.raises(MeasureRefused, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-267 | `tests/unit/test_preview_meter.py:52` | check_allowed("kiosk") | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-268 | `tests/unit/test_preview_meter.py:55` | def test_worker_configs_refuse_measure_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-269 | `tests/unit/test_preview_meter.py:58` | replace(vision, mode="kiosk", camera_preview="public", measure=True).validate() | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-270 | `tests/unit/test_preview_meter.py:59` | audio = AudioWorkerConfig.from_settings(audio_settings("kiosk"), VALUES) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-271 | `tests/unit/test_preview_meter.py:64` | def test_run_refuses_measure_in_kiosk(capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-272 | `tests/unit/test_preview_meter.py:67` | s = _settings("kiosk") | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-273 | `tests/unit/test_preview_meter.py:69` | assert "kiosk" in capsys.readouterr().err | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-274 | `tests/unit/test_preview_meter.py:182` | assert not WebUi(s.ui, dev=False, measure=True).measure  # kiosk: tidak pernah aktif | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-275 | `tests/unit/test_prompt_per_provider.py:131` | kiosk = yaml.safe_load((ROOT / "config" / "kiosk.yaml").read_text(encoding="utf-8")) | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-276 | `tests/unit/test_prompt_per_provider.py:132` | assert kiosk["llm"]["prompt_variants"] == {}  # kiosk butuh nilai TBD; cek isi YAML saja | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-277 | `tests/unit/test_prompt_v4.py:387` | def _kiosk_settings(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-278 | `tests/unit/test_prompt_v4.py:389` | return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-279 | `tests/unit/test_prompt_v4.py:392` | def test_with_prompt_variant_rejected_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-280 | `tests/unit/test_prompt_v4.py:394` | webui_app.with_prompt_variant(_kiosk_settings(), "v4") | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-281 | `tests/unit/test_prompt_v4.py:397` | def test_main_prompt_variant_kiosk_exit_2(monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-282 | `tests/unit/test_prompt_v4.py:398` | monkeypatch.setattr(webui_app, "load_settings", lambda *a, **k: _kiosk_settings()) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-283 | `tests/unit/test_prompt_v5.py:130` | @pytest.mark.parametrize("name", ["dev.yaml", "kiosk.yaml"]) | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-284 | `tests/unit/test_push_to_talk.py:221` | for name in ("dev", "kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-285 | `tests/unit/test_push_to_talk.py:275` | from mica.core.controller import KioskController | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-286 | `tests/unit/test_push_to_talk.py:292` | c = KioskController(bus, s, object(), lambda item: None) | K1 | ganti nama: KioskController -> AppController | nama ada di SDD (7x); impor di banyak file |
| K1-287 | `tests/unit/test_resources.py:43` | check_allowed("kiosk", True) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-288 | `tests/unit/test_resources.py:45` | check_allowed("kiosk", False) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-289 | `tests/unit/test_resources.py:47` | make_recorder(Path("x"), "kiosk", False, dict) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-290 | `tests/unit/test_resources.py:100` | rec = make_recorder(tmp_path / "run", "kiosk", True, dict, interval_s=0.05, | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-291 | `tests/unit/test_resources.py:106` | assert info["e09"] is True and info["app_mode"] == "kiosk" and info["interval_s"] == 0.05 | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-292 | `tests/unit/test_resources.py:116` | def _kiosk_settings(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-293 | `tests/unit/test_resources.py:118` | return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-294 | `tests/unit/test_resources.py:121` | def test_webui_run_refuses_recorder_in_kiosk_without_e09(tmp_path, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-295 | `tests/unit/test_resources.py:124` | code = run(_kiosk_settings(), no_browser=True, record_resources=tmp_path / "r") | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-296 | `tests/unit/test_resources.py:137` | assert entry.main(["--record-resources", "r"], check=lambda c, e: (ok, _kiosk_settings()), | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-297 | `tests/unit/test_resources.py:141` | check=lambda c, e: (ok, _kiosk_settings()), launch=launch) == 0  # fmt: skip | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-298 | `tests/unit/test_setup_check.py:23` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-299 | `tests/unit/test_setup_check.py:124` | settings = load_settings(KIOSK_YAML, require_complete=False) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-300 | `tests/unit/test_setup_check.py:181` | def test_check_kiosk_nulls_listed_by_key(tmp_path, locked, monkeypatch): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-301 | `tests/unit/test_setup_check.py:182` | rows, settings = _run(tmp_path, KIOSK_YAML, monkeypatch) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-302 | `tests/unit/test_setup_check.py:214` | assert "kiosk tetap bisa dipakai lewat teks" in by_item["perangkat audio"].message | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-303 | `tests/unit/test_setup_check.py:284` | rows = [check.CheckRow("config", "GAGAL", "mode kiosk: 1 kunci belum diisi: x")] | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-304 | `tests/unit/test_setup_check.py:292` | def test_main_check_ok_launches_with_default_kiosk_config(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-305 | `tests/unit/test_setup_check.py:302` | assert seen["config"] == Path("config/kiosk.yaml") | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-306 | `tests/unit/test_setup_check.py:318` | def test_main_rejects_fake_flags_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-307 | `tests/unit/test_setup_check.py:320` | kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-308 | `tests/unit/test_setup_check.py:322` | code = entry.main(["--fake-workers"], check=lambda c, e: (ok, kiosk), | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-309 | `tests/unit/test_setup_check.py:436` | # pertanyaan chip di config/dev.yaml dan kiosk.yaml tidak identik/mirip data/eval | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-310 | `tests/unit/test_setup_check.py:443` | for name in ("dev.yaml", "kiosk.yaml"): | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-311 | `tests/unit/test_stt.py:416` | def test_listen_refused_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-312 | `tests/unit/test_stt.py:418` | kiosk = s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-313 | `tests/unit/test_stt.py:421` | cli.cmd_listen(args, kiosk, mic_factory=lambda d: FakeMic([])) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-314 | `tests/unit/test_trial.py:2` | dev saja (kiosk ditolak), peringatan berisi kunci + nilai, label UI, pemilihan pekerja asli/palsu, | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-315 | `tests/unit/test_trial.py:22` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-316 | `tests/unit/test_trial.py:56` | def test_trial_values_rejected_in_kiosk(capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-317 | `tests/unit/test_trial.py:58` | trial.load_trial_settings(KIOSK_YAML) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-318 | `tests/unit/test_trial.py:59` | assert webui_app.main(["--config", str(KIOSK_YAML), "--trial-values"]) == 2 | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-319 | `tests/unit/test_trial.py:78` | assert mica_main(["--config", str(KIOSK_YAML), "--trial-values"], check, launch) == 2 | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-320 | `tests/unit/test_trial.py:79` | assert len(launched) == 1  # kiosk tidak diluncurkan | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-321 | `tests/unit/test_tts.py:20` | KIOSK_YAML = ROOT / "config" / "kiosk.yaml" | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-322 | `tests/unit/test_tts.py:50` | def _kiosk_settings(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-323 | `tests/unit/test_tts.py:52` | return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-324 | `tests/unit/test_tts.py:97` | for path in (DEV_YAML, KIOSK_YAML): | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-325 | `tests/unit/test_tts.py:101` | assert "threads" in tts  # docs/CPU-THREADS.md; nilai dev boleh hasil pilih, kiosk null | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-326 | `tests/unit/test_tts.py:102` | assert yaml.safe_load(KIOSK_YAML.read_text(encoding="utf-8"))["audio"]["tts"]["threads"] is None | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-327 | `tests/unit/test_tts.py:109` | def test_length_scale_null_allowed_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-328 | `tests/unit/test_tts.py:110` | from test_config import _complete_kiosk_raw, _write | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-329 | `tests/unit/test_tts.py:112` | raw = _complete_kiosk_raw() | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-330 | `tests/unit/test_tts.py:115` | assert settings.app.mode == "kiosk" and settings.audio.tts.length_scale is None | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-331 | `tests/unit/test_tts.py:152` | def test_fetch_voice_refused_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-332 | `tests/unit/test_tts.py:154` | cli.cmd_fetch_voice(_kiosk_settings(), tmp_path, lambda u, d: None) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-333 | `tests/unit/test_tts.py:213` | def test_say_refused_in_kiosk(tmp_path): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-334 | `tests/unit/test_tts.py:216` | cli.cmd_say(args, _kiosk_settings(), tts_factory=FakeTts) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-335 | `tests/unit/test_types.py:94` | assert ErrorCode.CFG_GEMINI_IN_KIOSK == "CFG_GEMINI_IN_KIOSK" | K1 | ganti nama: CFG_GEMINI_IN_KIOSK -> CFG_GEMINI_IN_PROD | kode galat ada di SDD dan di log lama |
| K1-336 | `tests/unit/test_ui_window.py:157` | kiosk = MainWindow(_ui(), dev=False) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-337 | `tests/unit/test_ui_window.py:159` | qtbot.addWidget(kiosk) | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-338 | `tests/unit/test_ui_window.py:161` | assert kiosk.debug_panel is None and kiosk.findChild(object, "debug_dock") is None | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-339 | `tests/unit/test_ui_window.py:168` | kiosk.show_debug(DebugInfo(V.IDLE))  # tanpa panel: tidak error | K1+K3 | hapus bersama kode PySide6 (lihat K3) | lihat K3 |
| K1-340 | `tests/unit/test_vision_demo.py:267` | def _kiosk_settings(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-341 | `tests/unit/test_vision_demo.py:269` | return settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-342 | `tests/unit/test_vision_demo.py:272` | def test_demo_refused_in_kiosk(monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-343 | `tests/unit/test_vision_demo.py:273` | monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings()) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-344 | `tests/unit/test_vision_demo.py:280` | def test_fetch_model_refused_in_kiosk(monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-345 | `tests/unit/test_vision_demo.py:281` | monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings()) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-346 | `tests/unit/test_vision_demo.py:457` | def test_fetch_colors_refused_in_kiosk(monkeypatch, capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-347 | `tests/unit/test_vision_demo.py:458` | monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings()) | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-348 | `tests/unit/test_webui.py:565` | "--kiosk", url, "--edge-kiosk-type=fullscreen"]  # fmt: skip | K1+K2 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-349 | `tests/unit/test_webui.py:568` | assert not set(RENDERING_SWITCHES) & set(plain) and "--kiosk" in plain | K1+K2 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-350 | `tests/unit/test_webui.py:594` | assert cmd.index("--disable-gpu-compositing") < cmd.index("--kiosk") | K1+K2 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-351 | `tests/unit/test_webui.py:702` | assert browser.alive() and "--kiosk" in started[0] and browser.profile.is_dir() | K1+K2 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-352 | `tests/unit/test_webui.py:709` | def test_fakes_refused_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-353 | `tests/unit/test_webui.py:711` | kiosk = s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-354 | `tests/unit/test_webui.py:712` | with pytest.raises(WebUiError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-355 | `tests/unit/test_webui.py:713` | build_controller(kiosk, WebUi(kiosk.ui, dev=False), fake_workers=True) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-356 | `tests/unit/test_webui.py:714` | with pytest.raises(WebUiError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-357 | `tests/unit/test_webui.py:715` | build_controller(kiosk, WebUi(kiosk.ui, dev=False), fake_pipeline=True) | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-358 | `tests/unit/test_webui.py:749` | def test_run_refuses_fakes_in_kiosk(capsys): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-359 | `tests/unit/test_webui.py:753` | kiosk = s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-360 | `tests/unit/test_webui.py:754` | assert run(kiosk, fake_workers=True, no_browser=True) == 2 | K1 | ganti nama/teks ikut kode (kiosk -> prod) | rendah; tes tetap sama perilakunya |
| K1-361 | `tests/unit/test_webui.py:755` | assert "kiosk" in capsys.readouterr().err | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-362 | `tests/unit/test_worker_preview.py:80` | def test_preview_rejected_in_kiosk(): | K1 | ganti nama identifier: *_kiosk* -> *_prod* | API internal; tes ikut diganti |
| K1-363 | `tests/unit/test_worker_preview.py:81` | with pytest.raises(WorkerConfigError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-364 | `tests/unit/test_worker_preview.py:82` | VisionWorkerConfig.from_settings(_settings("kiosk"), TEST_VALUES, preview=True) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-365 | `tests/unit/test_worker_preview.py:84` | forged = VisionWorkerConfig(**{**cfg.__dict__, "mode": "kiosk"}) | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-366 | `tests/unit/test_worker_preview.py:85` | with pytest.raises(WorkerConfigError, match="kiosk"): | K1 | ganti nilai: app.mode kiosk -> prod | nilai config; mengubah config_hash; tes ikut diganti |
| K1-367 | `scripts/compare_models.py:21` | (TokenRateLimiter, sampai sekitar 60 detik), yang tidak ada di kiosk. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-368 | `scripts/l40_startup.ps1:4` | # Tiap ulangan: python -m mica (check, pekerja kamera dan suara asli, pipeline asli, Edge kiosk) | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-369 | `scripts/startup_profile.py:11` | kiosk) dengan MICA_STARTUP_LOG ke folder ulangan. --fake-camera: python -m mica.webui | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-370 | `scripts/ui_ab_bench.py:5` | Bench tahap 1 yang sama (ui_bench.run_once: Edge kiosk, diam 60 s lalu 20 pertanyaan, pekerja | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-371 | `scripts/ui_bench.py:54` | FACTOR = 3.0  # protokol: perkiraan laptop kiosk ~1/3 laptop dev | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-372 | `scripts/ui_bench.py:169` | kiosk = build(settings, fake_workers=True, fake_pipeline=True) | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-373 | `scripts/ui_bench.py:170` | window, controller = kiosk.window, kiosk.controller | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-374 | `scripts/ui_bench.py:223` | kiosk.timer.start() | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-375 | `scripts/ui_bench.py:271` | # --edge-extra: switch kandidat disisipkan sebelum --kiosk/URL tanpa mengubah kode aplikasi | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-376 | `scripts/ui_bench.py:884` | "Edge kiosk layar penuh (--kiosk --edge-kiosk-type=fullscreen)": settings.ui.fullscreen, | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-377 | `scripts/ui_preview_bench.py:1` | """Ukur ulang UI kiosk baru (Langkah 37): kondisi 1 vs baseline putaran 2, kondisi 2 vs kondisi 1. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-378 | `scripts/ui_preview_bench.py:8` | - Bench tahap 1 yang sama (ui_bench.run_once: Edge kiosk, diam 60 s lalu 20 pertanyaan, AC | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-379 | `scripts/ui_preview_bench.py:135` | lines = ["# Langkah 37: ukur ulang UI kiosk", "", | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-380 | `scripts/ui_preview_opt.py:14` | - grow: satu proses anak bench (Edge kiosk, pekerja suara/pipeline palsu, proses kamera dengan | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-381 | `docs/CPU-THREADS.md:79` | - Diukur di laptop dev. Nilai kiosk **dipilih ulang dengan aturan yang sama di E-09**. Grid E-09 | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-382 | `docs/E-04.md:10` | - Gemini hanya pembanding kualitas. Gemini gugur untuk kiosk karena kendala keras (syarat tier | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-383 | `docs/E-04.md:11` | gratis; SDD 8.2, N-09), sehingga hasil E-04 **tidak mengubah model kiosk** (llm.chain | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-384 | `docs/E-04.md:12` | kiosk tetap Groq). Hasilnya dipakai untuk menjelaskan berapa kualitas yang dilepas karena | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-385 | `docs/E-04.md:15` | ditolak di kiosk). | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-386 | `docs/E-05.md:8` | > Aturan E-05 ditetapkan sebelum data: syarat p95 waktu sampai transkripsi tampil paling lama 3 detik di lapto | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-387 | `docs/E-05.md:11` | otomatis. Syarat p95 hanya sah bila diukur di laptop kiosk. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-388 | `docs/E-05.md:21` | - Rekam di ruangan dan dengan mikrofon yang sama dengan kiosk bila memungkinkan; catat | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-389 | `docs/E-05.md:35` | 1. Tujuan: suara direkam untuk mengukur ketepatan pengenalan ucapan MICA (kiosk informasi PMB | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-390 | `docs/E-07.md:16` | - images/: frame JPG/PNG dari kamera kiosk (atau kamera yang sama jenisnya). | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-391 | `docs/E-07.md:38` | - klip video (mis. MP4) dari kamera kiosk, laju frame tetap; | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-392 | `docs/E-07.md:47` | \| masuk \| ya \| Detik klip saat orang mulai terlihat di depan kiosk \| | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-393 | `docs/E-07.md:48` | \| berhenti \| untuk berhenti \| Detik klip saat orang mulai berhenti di depan kiosk \| | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-394 | `docs/E-07.md:49` | \| pergi \| ya \| Detik klip saat orang pergi (keluar dari depan kiosk) \| | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-395 | `docs/E-07.md:58` | README.md dan .gitkeep di repo), perintah eval menolak berjalan di mode kiosk, dan semua | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-396 | `docs/E-07.md:67` | orang, sapaan, dan penamaan warna baju MICA (kiosk informasi PMB Universitas Mikroskil) | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-397 | `docs/E-07.md:69` | 2. Yang direkam: relawan berjalan lewat, berhenti, pergi, dan kembali di depan kamera kiosk | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-398 | `docs/E-07.md:170` | - Satu lokasi (lokasi kiosk), sehingga hasil tidak menggeneralisasi ke ruangan lain. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-399 | `docs/E-07.md:180` | - Kiosk wajib memakai model dengan keypoint: ADR-13 mengambil area baju dari bahu dan pinggul, | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-400 | `docs/E-08.md:39` | deteksi itu dipakai oleh kedua region, sama seperti di kiosk. Kotak label tanpa pasangan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-401 | `docs/E-09.md:11` | 17 Okt 2026) di laptop kiosk atau laptop yang mirip. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-402 | `docs/E-09.md:18` | (Flask + Edge kiosk). Tanpa --fake-workers atau --fake-pipeline. | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-403 | `docs/E-09.md:87` | - Kiosk dijalankan satu hari uji penuh dengan konfigurasi hasil kalibrasi. Jam mulai dan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-404 | `docs/E-09.md:104` | - Spesifikasi laptop kiosk belum diketahui. Bila E-09 diukur di laptop dev, hasilnya hanya | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-405 | `docs/E-09.md:111` | Ditetapkan sebelum data E-09 dikumpulkan (Langkah 37, UI kiosk baru dengan pratinjau kamera). | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-406 | `docs/E-09.md:113` | - E-09 diukur dengan ui.camera_preview = public (nilai kiosk.yaml), karena kiosk memakai | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-407 | `docs/E-09.md:125` | input suara menjadi push-to-talk (audio.input_mode: push_to_talk, bawaan dev dan kiosk; | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-408 | `docs/FOLLOWUP.md:90` | Pemenang dipasang di rag.followup_mode (config/dev.yaml dan config/kiosk.yaml) dengan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-409 | `docs/FOLLOWUP.md:145` | - config/kiosk.yaml ikut dual. Mode ini memakai rag.rrf_k dan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-410 | `docs/FOLLOWUP.md:146` | rag.candidates_per_retriever, yang di kiosk masih null (menunggu E-01). Selama keduanya | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-411 | `docs/FOLLOWUP.md:147` | belum diisi, kiosk tetap tidak lolos mica check, sama seperti sebelumnya. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-412 | `docs/KB-RESMI.md:4` | config/dev.yaml dan config/kiosk.yaml (kb.active_id), bersama prompt **v5** | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-413 | `docs/KB-RESMI.md:53` | - rag.source_priority: [pmb] di config/dev.yaml dan config/kiosk.yaml. Ini nilai | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-414 | `docs/KB-RESMI.md:535` | resmi (rag.gate.threshold di config/dev.yaml; di config/kiosk.yaml tetap null/TBD). | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-415 | `docs/KIOSK.md:1` | # Memasang MICA di laptop kiosk | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-416 | `docs/KIOSK.md:3` | Urutan di bawah dijalankan sekali di laptop kiosk (Windows, Python 3.11 atau lebih baru), dari | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-417 | `docs/KIOSK.md:4` | PowerShell. Perintah yang mengunduh hanya pip install dan python -m mica setup; saat kiosk | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-418 | `docs/KIOSK.md:51` | 6. Jalankan kiosk: | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-419 | `docs/KIOSK.md:59` | UI kiosk adalah UI web (ui.backend: web): MICA menjalankan server lokal di 127.0.0.1 | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-420 | `docs/KIOSK.md:60` | lalu membuka Microsoft Edge dalam mode kiosk layar penuh. Edge tidak perlu dibuka sendiri. | K1+K2 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-421 | `docs/KIOSK.md:61` | Untuk menutup kiosk, tekan Alt+F4 di jendela Edge (server dan proses kamera/suara ikut | K1+K2 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-422 | `docs/KIOSK.md:69` | menulis baris Microsoft Edge  GAGAL dan kiosk tidak dijalankan. Edge memakai profil | K1+K2 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-423 | `docs/KIOSK.md:71` | kiosk ditutup. | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-424 | `docs/KIOSK.md:75` | - Tanpa argumen, ketiga perintah memakai config/kiosk.yaml. Untuk mode pengembangan pakai | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-425 | `docs/KIOSK.md:77` | - config/kiosk.yaml baru lolos check setelah semua nilai TBD diisi dari hasil eksperimen | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-426 | `docs/KIOSK.md:90` | - Bila pipeline gagal dimuat (mis. KB rusak), kiosk tetap berjalan. Setiap pertanyaan dijawab | K1 | ganti nama file -> docs/PEMASANGAN.md, tulis ulang untuk web app | tautan dari README/PERINTAH ikut diubah |
| K1-427 | `docs/PERINTAH.md:5` | app.mode: kiosk. | K1 | ganti kata: kiosk -> web app / prod | rendah |
| K1-428 | `docs/PERINTAH.md:7` | ## 1. Pemasangan (sekali, lihat docs/KIOSK.md) | K1 | ganti kata: kiosk -> web app / prod | rendah |
| K1-429 | `docs/PERINTAH.md:24` | python -m mica                                        # kiosk (config/kiosk.yaml) | K1 | ganti kata: kiosk -> web app / prod | rendah |
| K1-430 | `docs/PROMPT-V4.md:58` | - Uji coba langsung: python -m mica.webui --prompt-variant v2\|v3\|v4 (dev saja; kiosk ditolak | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-431 | `docs/PROMPT-V4.md:136` | Sampai itu, bawaan config/dev.yaml dan config/kiosk.yaml tetap rag.prompt_variant: | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-432 | `docs/PROMPT-V4.md:153` | kesepakatannya dulu. llm.prompt_variants di config/dev.yaml dan config/kiosk.yaml tetap | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-433 | `docs/UI-PREVIEW-OPT.md:11` | Edge 53,9 -> 213,8 MB) dan CPU diam +8,91 poin. Laptop kiosk lebih lemah dari laptop dev, jadi | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-434 | `docs/UI-PREVIEW-OPT.md:49` | Bench tahap 1 yang sama (scripts/ui_bench.py run_once): Edge kiosk, diam 60 s, lalu 20 | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-435 | `docs/UI-PREVIEW-OPT.md:110` | yang relevan untuk kiosk. Kandidat K1 dan K2 tidak diubah; K3 tidak ada. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-436 | `docs/ui-screens/README.md:1` | # Tangkapan layar UI kiosk | K1 | ganti kata: kiosk -> web app / prod | rendah |
| K1-437 | `docs/UI-WEB.md:10` | berstatus Provisional. Kedua UI memakai KioskController dan ViewModel yang sama; yang dibandingkan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-438 | `docs/UI-WEB.md:19` | - layar penuh lewat Edge kiosk; | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-439 | `docs/UI-WEB.md:29` | - ×3 adalah perkiraan pemilik proyek bahwa laptop kiosk kira-kira 1/3 kecepatan laptop dev | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-440 | `docs/UI-WEB.md:39` | ## Tahap 2: E-09, laptop kiosk nyata, kamera dan suara asli | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-441 | `docs/UI-WEB.md:58` | dan kiosk.yaml sampai E-09; pilihan akhir mengikuti aturan tahap 2 di atas. Aturan tahap 1 dan | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-442 | `docs/UI-WEB.md:101` | - Risiko dibatasi dengan: bind hanya 127.0.0.1, satu pengguna lokal (Edge di laptop kiosk), Origin | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-443 | `docs/UI-WEB.md:128` | - Notepad yang dimaksimalkan menutup 95% jendela Edge kiosk (1536 × 864). Sisanya, strip | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-444 | `docs/UI-WEB.md:144` | - UI web (Flask + Edge kiosk) dipilih sebagai UI utama MICA sebelum tahap 2. Dasarnya data | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-445 | `docs/UI-WEB.md:147` | Penyimpangan ini wajib diungkap di Bab 3. ui.backend: web di dev.yaml dan kiosk.yaml. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-446 | `docs/UI-WEB.md:177` | ## Sistem desain UI kiosk (Langkah 37, 18 Okt 2026) | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-447 | `docs/UI-WEB.md:226` | ## Pratinjau kamera UI kiosk (Langkah 37, 18 Okt 2026) | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-448 | `docs/UI-WEB.md:228` | - ui.camera_preview: off \| public \| debug. kiosk.yaml public, dev.yaml debug; config | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-449 | `docs/UI-WEB.md:229` | menolak debug saat app.mode: kiosk. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-450 | `docs/UI-WEB.md:377` | Hasil: results/ADR-19/ui-preview-opt-20261018-1712. Bench tahap 1 (Edge kiosk, diam 60 s lalu 20 | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-451 | `docs/UI-WEB.md:399` | dev.yaml dan kiosk.yaml (bukan hasil eksperimen). Laju deteksi YOLO tidak diubah. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-452 | `docs/UI-WEB.md:403` | berjalan). Kamera laptop kiosk dicek ulang di E-09. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-453 | `docs/UI-WEB.md:420` | asli di laptop kiosk diukur di E-09. | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-454 | `docs/UI-WEB.md:421` | - K2 diukur di Edge laptop dev. Efeknya di Edge/GPU laptop kiosk perlu dicek ulang di E-09. | K1+K2 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-455 | `docs/UI-WEB.md:475` | python -m mica.webui --prompt-variant v2\|v3\|v4 (dev saja, kiosk ditolak kode 2), dengan label | K1 | biarkan: catatan eksperimen/pra-reg, menggambarkan kondisi saat itu | mengubah = mengubah catatan sejarah |
| K1-456 | `README.md:3` | Kiosk informasi Penerimaan Mahasiswa Baru (PMB) Universitas Mikroskil, dibuat untuk skripsi S-1. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-457 | `README.md:8` | - Pemasangan di laptop kiosk: [docs/KIOSK.md](docs/KIOSK.md) | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-458 | `README.md:13` | - Windows 10/11 dan Microsoft Edge. UI kiosk berjalan di Edge mode kiosk. | K1+K2 | ganti kata; lihat K2 untuk peluncur Edge | lihat K2 |
| K1-459 | `README.md:63` | python -m mica                                    # mode kiosk (config/kiosk.yaml) | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-460 | `README.md:66` | Mode kiosk baru lolos check kalau semua nilai TBD (null) di config/kiosk.yaml sudah diisi | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-461 | `README.md:82` | - config/kiosk.yaml: untuk kiosk. Tanpa Gemini, dan nilai TBD wajib diisi sebelum dipakai. | K1 | ganti: config/kiosk.yaml -> config/prod.yaml | path default CLI; dokumen lama merujuk kiosk.yaml |
| K1-462 | `README.md:95` | config/     konfigurasi dev dan kiosk | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-463 | `README.md:97` | docs/       SDD, catatan eksperimen (E-xx), panduan kiosk, tangkapan layar UI | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-464 | `README.md:104` | core/     controller kiosk, sesi, bus antarproses, logging | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-465 | `README.md:114` | - Di mode kiosk, frame kamera dan audio mikrofon tidak pernah disimpan ke disk. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-466 | `.env.example:3` | # Gemini hanya untuk mode dev (app.mode: dev); jangan dipakai di mode kiosk. | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
| K1-467 | `pyproject.toml:8` | description = "MICA: kiosk informasi PMB Universitas Mikroskil" | K1 | ganti kata: kiosk -> prod / aplikasi | rendah (komentar/pesan) |
