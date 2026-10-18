# Tabel transisi M-09 (diekspor dari mica.core.session.TRANSITIONS)

Setiap baris diuji di tests/unit/test_session.py (urutan aksi dan state tujuan).
ShowView adalah potret tampilan; Ignored = dicatat di log debug oleh M-10.

| ID | Dari | Event | Syarat | Aksi | Ke | Sumber |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | IDLE | PersonArrived | Jeda sapaan ulang sudah lewat | Speak, SetVisionRate, ListenControl, ShowView | GREETING | SDD 7.1 |
| T02 | IDLE | PersonArrived | Masih dalam jeda sapaan ulang | Ignored | IDLE | SDD 7.1 |
| T03 | IDLE | TopicTapped / TextSubmitted | Teks tidak kosong | ShowView, RunPipeline | THINKING | SDD 7.1 |
| T04 | GREETING | SpeechDone | utterance_id sapaan | ListenControl, ShowView | READY | SDD 7.1 |
| T05 | READY | SpeechStarted | - | ShowView | LISTENING | SDD 7.1 |
| T06 | READY | TopicTapped / TextSubmitted | Teks tidak kosong | ShowView, RunPipeline | THINKING | SDD 7.1 |
| T07 | LISTENING | Transcript | ok dan teks tidak kosong | ShowView, ListenControl, Speak, RunPipeline | THINKING | SDD 7.1 |
| T08 | LISTENING | Transcript | Gagal atau kosong, filtered_by None | ShowView | READY | SDD 7.1 |
| T09 | LISTENING | Transcript | filtered_by tidak None | Ignored | LISTENING | Langkah 22 |
| T10 | THINKING | AnswerReady | session_id cocok; tambah history | ShowView, Speak | SPEAKING | SDD 7.1 |
| T11 | THINKING | TextSubmitted | - | Ignored | THINKING | SDD 7.1 |
| T12 | SPEAKING | SpeechDone | utterance_id jawaban | ListenControl, ShowView | READY | SDD 7.1 |
| T13 | SPEAKING | StopTapped | - | StopSpeaking, ListenControl, ShowView | READY | SDD 7.1 + ListenControl(auto) |
| T14 | Semua kecuali IDLE | PersonLeft | - | StopSpeaking, ClearScreen, ListenControl, SetVisionRate, ShowView | IDLE | SDD 7.1 + ListenControl(off) |
| T15 | Semua kecuali IDLE | Tick (IdleTimeout) | now - interaksi terakhir > idle_reset_s | StopSpeaking, ClearScreen, ListenControl, SetVisionRate, ShowView | IDLE | SDD 7.1 + ListenControl(off) |
| T18 | GREETING | TopicTapped / TextSubmitted | Teks tidak kosong | StopSpeaking, ListenControl, ShowView, RunPipeline | THINKING | Keputusan 17 Okt (N-10) |
| T19 | LISTENING | TopicTapped / TextSubmitted | Teks tidak kosong | ListenControl, ShowView, RunPipeline | THINKING | Keputusan 17 Okt (N-10) |
| T20 | READY | TalkTapped | - | ListenControl, ShowView | READY | Langkah 24 (push-to-talk, M-08) |
| P01 | IDLE | TalkPressed | input_mode push_to_talk; session_id baru | ListenControl, ShowView | LISTENING | Langkah 42 (keputusan 18 Okt) |
| P02 | READY | TalkPressed | input_mode push_to_talk | ListenControl, ShowView | LISTENING | Langkah 42 (keputusan 18 Okt) |
| P03 | GREETING / SPEAKING | TalkPressed | input_mode push_to_talk; barge-in, SpeechDone nanti diabaikan | StopSpeaking, ListenControl, ShowView | LISTENING | Langkah 42 (keputusan 18 Okt) |
| P04 | LISTENING | TalkReleased | input_mode push_to_talk | ReleaseTalk, ShowView | LISTENING | Langkah 42 (keputusan 18 Okt) |
| P05 | LISTENING | TalkCancelled | input_mode push_to_talk | ListenControl, ShowView | READY | Langkah 42 (keputusan 18 Okt) |
| P06 | LISTENING | Transcript | input_mode push_to_talk; filtered_by tidak None | ShowView | READY | Langkah 42 (keputusan 18 Okt) |
| P07 | THINKING / LISTENING | TalkPressed | input_mode push_to_talk; tidak bisa merekam | Ignored | Tetap | Langkah 42 |
| P08 | Semua | TalkPressed / TalkReleased / TalkCancelled | input_mode vad | Ignored | Tetap | Langkah 42 |
| T16 | Semua | SpeechStarted / Transcript / SpeechDone / AnswerReady | session_id lama | Ignored | Tetap | SDD 3.3, 5.2 |
| T17 | Semua | Event lain | - | Ignored | Tetap | SDD 7.1 |
| R01 | IDLE | CameraStatus(ok=True) | Sebelumnya ok=False (restart) | SetVisionRate, ShowView | IDLE | Keputusan 17 Okt |
| R02 | Semua kecuali IDLE | CameraStatus(ok=True) | Sebelumnya ok=False (restart) | SetVisionRate, ShowView | Tetap | Keputusan 17 Okt |
| R03 | Semua kecuali IDLE | PersonArrived | Setelah restart vision, sampai sesi berakhir | Ignored | Tetap | Keputusan 17 Okt |
| R04 | GREETING / SPEAKING / LISTENING | AudioStatus(ready=True) | Setelah tidak siap (restart) | ListenControl, ShowView | READY | Keputusan 17 Okt |
| R05 | READY | AudioStatus(ready=True) | Setelah tidak siap (restart) | ListenControl, ShowView | READY | Keputusan 17 Okt |
| R06 | IDLE / THINKING | AudioStatus(ready=True) | Setelah tidak siap (restart); ListenControl(off) | ListenControl, ShowView | Tetap | Keputusan 17 Okt |
| D01 | Semua | CameraStatus(ok=False) | Sebelumnya ok/belum ada | ShowView | Tetap | Langkah 22 |
| D02 | Semua | AudioStatus(mic_ok berubah) | Bukan restart | ShowView | Tetap | Langkah 22 |
