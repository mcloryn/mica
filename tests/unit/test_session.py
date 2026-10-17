"""M-09 Session: satu tes per baris TRANSITIONS (SDD 7.1 + aturan restart), skenario, properti.

Angka di sini data uji (bukan ambang): fps_busy 2, min_majority 0,5, idle 30 s, jeda 10 s.
"""

import itertools
from pathlib import Path

import pytest

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.config import load_settings
from mica.core import texts
from mica.core.bus import SetVisionRate
from mica.core.session import (
    NON_IDLE,
    TRANSITIONS,
    AnswerReady,
    ClearScreen,
    Ignored,
    RunPipeline,
    Session,
    ShowView,
    StopTapped,
    TextSubmitted,
    Tick,
    TopicTapped,
    VisitState,
    transitions_markdown,
)
from mica.core.types import FinalAnswer
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft

ROOT = Path(__file__).resolve().parents[2]
V = VisitState
ALL = list(VisitState)
BUSY = [s for s in VisitState if s != V.IDLE]
FPS_IDLE, FPS_BUSY, MAJORITY, IDLE_S, COOLDOWN_S = 5.0, 2.0, 0.5, 30.0, 10.0


def make(**kw):
    ids = (f"s{i}" for i in itertools.count())
    args = {"fps_idle": FPS_IDLE, "fps_busy": FPS_BUSY, "min_majority": MAJORITY,
            "idle_reset_s": IDLE_S, "regreet_cooldown_s": COOLDOWN_S, **kw}  # fmt: skip
    return Session(**args, new_session_id=lambda: next(ids))


def arrived(color="merah", conf=0.9):
    return PersonArrived(1, (0.0, 0.0, 10.0, 10.0), 0.0, color, conf)


def answer(text="Biaya Sistem Informasi Rp7.500.000 per tahun."):
    return FinalAnswer("answered", text, (), {})


def names(actions):
    return tuple(type(a).__name__ for a in actions)


def of(actions, kind):
    return [a for a in actions if isinstance(a, kind)]


def drive(state, s=None):
    """Session di state itu lewat jalur suara utama; waktu 0..4."""
    s = s or make()
    if state == V.IDLE:
        return s
    s.handle(arrived(), 0.0)
    if state == V.GREETING:
        return s
    s.handle(SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)
    if state == V.READY:
        return s
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    if state == V.LISTENING:
        return s
    s.handle(Transcript(s.session_id, "biaya kuliah berapa", True, 0.5, 1.5), 3.0)
    if state == V.THINKING:
        return s
    s.handle(AnswerReady(s.session_id, answer()), 4.0)
    return s


def at(state):
    return lambda: drive(state)


def cooled():
    s = drive(V.READY)
    s.handle(PersonLeft(1, 5.0, 4.0), 5.0)  # jeda sapaan ulang sampai 15
    return s


def camera_down(state):
    def setup():
        s = drive(state)
        s.handle(CameraStatus(ok=False, message="WORKER_RESTART"), 4.5)
        return s

    return setup


def vision_restarted(state):
    def setup():
        s = camera_down(state)()
        s.handle(CameraStatus(ok=True, message="kamera 0 terbuka"), 4.6)
        return s

    return setup


def audio_down(state):
    def setup():
        s = drive(state)
        s.handle(AudioStatus(True, True, True, "siap"), 0.0)
        s.handle(AudioStatus(False, False, False, "WORKER_RESTART"), 4.5)
        return s

    return setup


def transcript(s, text="biaya kuliah berapa", ok=True, filtered=None):
    return Transcript(s.session_id, text, ok, 0.5, 1.5, False, filtered)


OK_CAM = CameraStatus(ok=True, message="kamera 0 terbuka")
READY_AUDIO = AudioStatus(True, True, True, "siap")

# id -> [(setup, event(s), now), ...]; "Tetap" = state awal
CASES = {
    "T01": [(at(V.IDLE), lambda s: arrived(), 0.0)],
    "T02": [(cooled, lambda s: arrived(), 6.0)],
    "T03": [(at(V.IDLE), lambda s: TopicTapped("Biaya", "Biaya kuliah berapa?"), 0.0),
            (at(V.IDLE), lambda s: TextSubmitted("Jalur masuk apa saja?"), 0.0)],
    "T04": [(at(V.GREETING), lambda s: SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)],
    "T05": [(at(V.READY), lambda s: SpeechStarted(s.session_id, 2.0), 2.0)],
    "T06": [(at(V.READY), lambda s: TopicTapped("Beasiswa", "Ada beasiswa apa?"), 2.0),
            (at(V.READY), lambda s: TextSubmitted("Akreditasi apa?"), 2.0)],
    "T07": [(at(V.LISTENING), transcript, 3.0)],
    "T08": [(at(V.LISTENING), lambda s: transcript(s, "", ok=False), 3.0),
            (at(V.LISTENING), lambda s: transcript(s, "   ", ok=True), 3.0)],
    "T09": [(at(V.LISTENING), lambda s: transcript(s, "", False, "no_speech"), 3.0),
            (at(V.LISTENING), lambda s: transcript(s, "", False, "min_speech"), 3.0)],
    "T10": [(at(V.THINKING), lambda s: AnswerReady(s.session_id, answer()), 4.0)],
    "T11": [(at(V.THINKING), lambda s: TextSubmitted("pertanyaan lain"), 4.0)],
    "T12": [(at(V.SPEAKING), lambda s: SpeechDone(s.session_id, s.answer_uid, 0.3), 5.0)],
    "T13": [(at(V.SPEAKING), lambda s: StopTapped(), 5.0)],
    "T14": [(at(st), lambda s: PersonLeft(1, 6.0, 5.0), 6.0) for st in BUSY],
    "T15": [(at(st), lambda s: Tick(100.0), 100.0) for st in BUSY],
    "T18": [(at(V.GREETING), lambda s: TextSubmitted("Biaya kuliah berapa?"), 0.5),
            (at(V.GREETING), lambda s: TopicTapped("Biaya", "Biaya kuliah berapa?"), 0.5)],
    "T19": [(at(V.LISTENING), lambda s: TextSubmitted("Jalur masuk apa saja?"), 2.5),
            (at(V.LISTENING), lambda s: TopicTapped("Jalur", "Jalur masuk apa saja?"), 2.5)],
    "T16": [(at(V.LISTENING), lambda s: Transcript("lama", "x", True, 0.1, 0.1), 3.0),
            (at(V.READY), lambda s: SpeechStarted("lama", 2.0), 2.0),
            (at(V.SPEAKING), lambda s: SpeechDone("lama", s.answer_uid, 0.1), 5.0),
            (at(V.THINKING), lambda s: AnswerReady("lama", answer()), 4.0)],
    "T17": [(at(V.IDLE), lambda s: StopTapped(), 0.0),
            (at(V.IDLE), lambda s: PersonLeft(1, 0.0, 1.0), 0.0),
            (at(V.GREETING), lambda s: StopTapped(), 0.5),
            (at(V.GREETING), lambda s: TextSubmitted("  "), 0.5),
            (at(V.LISTENING), lambda s: TopicTapped("Biaya", ""), 2.5),
            (at(V.READY), lambda s: SpeechDone(s.session_id, s.greeting_uid, 0.1), 2.0),
            (at(V.THINKING), lambda s: SpeechStarted(s.session_id, 3.5), 3.5),
            (at(V.SPEAKING), lambda s: arrived(), 5.0),
            (at(V.IDLE), lambda s: TextSubmitted("  "), 0.0)],
    "R01": [(camera_down(V.IDLE), lambda s: OK_CAM, 5.0)],
    "R02": [(camera_down(st), lambda s: OK_CAM, 5.0) for st in BUSY],
    "R03": [(vision_restarted(st), lambda s: arrived(), 5.0) for st in BUSY],
    "R04": [(audio_down(st), lambda s: READY_AUDIO, 5.0)
            for st in (V.GREETING, V.SPEAKING, V.LISTENING)],
    "R05": [(audio_down(V.READY), lambda s: READY_AUDIO, 5.0)],
    "R06": [(audio_down(st), lambda s: READY_AUDIO, 5.0) for st in (V.IDLE, V.THINKING)],
    "D01": [(at(st), lambda s: CameraStatus(ok=False, message="kamera putus"), 4.5) for st in ALL],
    "D02": [(at(st), lambda s: AudioStatus(False, True, True, "MIC_DOWN"), 4.5) for st in ALL],
}  # fmt: skip

ROWS = [(row, i) for row in TRANSITIONS for i in range(len(CASES[row.id]))]


def test_every_row_has_cases():
    assert sorted(CASES) == sorted(r.id for r in TRANSITIONS)


@pytest.mark.parametrize(("row", "i"), ROWS, ids=[f"{r.id}-{i}" for r, i in ROWS])
def test_transition_row(row, i):
    setup, event, now = CASES[row.id][i]
    s = setup()
    before = s.state
    actions = s.handle(event(s), now)
    assert names(actions) == row.actions
    expected = before if row.to == "Tetap" else VisitState(row.to)
    assert s.state == expected
    if row.frm not in ("Semua", NON_IDLE) and "/" not in row.frm:
        assert before == VisitState(row.frm)


# --- isi aksi -----------------------------------------------------------------------------


def test_greeting_names_color_only_when_confident():
    s = make()
    speak = of(s.handle(arrived("merah", 0.9), 0.0), Speak)[0]
    assert speak.text == texts.GREETING_COLOR.format(warna="merah")
    assert speak.session_id == s.session_id and speak.utterance_id == s.greeting_uid
    s = make()
    assert of(s.handle(arrived("merah", 0.4), 0.0), Speak)[0].text == texts.GREETING
    s = make(min_majority=None)  # null = tidak pernah menyebut warna
    assert of(s.handle(arrived("merah", 1.0), 0.0), Speak)[0].text == texts.GREETING
    s = make()
    assert of(s.handle(arrived(None, None), 0.0), Speak)[0].text == texts.GREETING


def test_greeting_actions_values():
    s = make()
    old = s.session_id
    actions = s.handle(arrived(), 0.0)
    assert s.session_id != old
    assert of(actions, SetVisionRate) == [SetVisionRate(FPS_BUSY)]
    assert of(actions, ListenControl) == [ListenControl("off", s.session_id)]


def test_fps_busy_null_sends_no_busy_rate():
    s = make(fps_busy=None)
    assert names(s.handle(arrived(), 0.0)) == ("Speak", "ListenControl", "ShowView")
    s = camera_down(V.READY)()
    s.fps_busy = None
    assert names(s.handle(OK_CAM, 5.0)) == ("ShowView",)


def test_voice_question_actions():
    s = drive(V.LISTENING)
    actions = s.handle(transcript(s), 3.0)
    view, listen, speak, run = actions
    assert view.transcript == "biaya kuliah berapa" and not view.send_enabled
    assert listen == ListenControl("off", s.session_id)
    assert speak.text == texts.FILLER
    assert run == RunPipeline(s.session_id, "biaya kuliah berapa", (), "voice")


def test_not_heard_message():
    s = drive(V.LISTENING)
    (view,) = s.handle(transcript(s, "", ok=False), 3.0)
    assert view.message == texts.NOT_HEARD and view.status == V.READY


def test_answer_shown_spoken_and_added_to_history_scrubbed():
    s = drive(V.LISTENING)
    s.handle(transcript(s, "nomor saya 081234567890, biaya berapa"), 3.0)
    view, speak = s.handle(AnswerReady(s.session_id, answer("Jawaban.")), 4.0)
    assert view.answer == "Jawaban." and speak.text == "Jawaban."
    assert speak.utterance_id == s.answer_uid
    (turn,) = s.history
    assert "081234567890" not in turn.question and turn.answer == "Jawaban."
    # pertanyaan berikutnya membawa history
    s.handle(SpeechDone(s.session_id, s.answer_uid, 0.2), 5.0)
    run = of(s.handle(TextSubmitted("kalau kelas sore?"), 6.0), RunPipeline)[0]
    assert run.history == s.history and run.input_mode == "text"


def test_reset_actions():
    s = drive(V.SPEAKING)
    old = s.session_id
    actions = s.handle(PersonLeft(1, 6.0, 5.0), 6.0)
    assert actions[0] == StopSpeaking(old)
    assert isinstance(actions[1], ClearScreen)
    assert actions[2] == ListenControl("off", s.session_id) and s.session_id != old
    assert actions[3] == SetVisionRate(FPS_IDLE)
    assert actions[4] == ShowView(V.IDLE)
    assert s.history == ()


# --- skenario -------------------------------------------------------------------------------


def test_scenario_a_main_voice_path():
    s = drive(V.READY)
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    assert s.state == V.LISTENING
    s.handle(transcript(s), 3.0)
    assert s.state == V.THINKING
    filler = s.view
    s.handle(SpeechDone(s.session_id, "u2", 0.1), 3.5)  # filler selesai: diabaikan
    assert s.state == V.THINKING and s.view == filler
    s.handle(AnswerReady(s.session_id, answer()), 4.0)
    assert s.state == V.SPEAKING
    actions = s.handle(SpeechDone(s.session_id, s.answer_uid, 0.2), 6.0)
    assert s.state == V.READY and of(actions, ListenControl)[0].mode == "auto"
    assert len(s.history) == 1


def test_scenario_b_text_while_camera_down():
    s = make()
    s.handle(CameraStatus(ok=False, message="kamera tidak terbuka"), 0.0)
    actions = s.handle(TextSubmitted("Biaya kuliah berapa?"), 1.0)
    assert s.state == V.THINKING and not actions[0].camera_ok
    s.handle(AnswerReady(s.session_id, answer()), 2.0)
    s.handle(SpeechDone(s.session_id, s.answer_uid, 0.2), 3.0)
    assert s.state == V.READY
    assert names(s.handle(Tick(3.0 + IDLE_S + 1), 3.0 + IDLE_S + 1))[0] == "StopSpeaking"
    assert s.state == V.IDLE  # sesi teks tetap direset walau kamera mati


def test_scenario_c_leave_while_thinking_drops_old_answer():
    s = drive(V.THINKING)
    old = s.session_id
    s.handle(PersonLeft(1, 4.0, 3.0), 4.0)
    actions = s.handle(AnswerReady(old, answer()), 5.0)
    assert names(actions) == ("Ignored",) and actions[0].reason == "session_id lama"
    assert s.state == V.IDLE and s.history == ()


def test_scenario_d_stop_tapped_while_speaking():
    s = drive(V.SPEAKING)
    actions = s.handle(StopTapped(), 5.0)
    assert actions[0] == StopSpeaking(s.session_id)
    assert actions[1] == ListenControl("auto", s.session_id)
    assert s.state == V.READY
    late = s.handle(SpeechDone(s.session_id, s.answer_uid, 0.2, interrupted=True), 5.1)
    assert names(late) == ("Ignored",) and s.state == V.READY


def test_scenario_e_vision_restart_while_ready_no_regreet():
    s = drive(V.READY)
    sid = s.session_id
    s.handle(CameraStatus(ok=False, message="WORKER_RESTART"), 3.0)
    assert s.handle(OK_CAM, 8.0)[0] == SetVisionRate(FPS_BUSY)
    assert names(s.handle(arrived(), 9.0)) == ("Ignored",)
    assert s.state == V.READY and s.session_id == sid
    # setelah sesi berakhir, sapaan diproses lagi (lewat jeda)
    s.handle(PersonLeft(1, 10.0, 9.0), 10.0)
    assert s.handle(arrived(), 10.0 + COOLDOWN_S)[0].text == texts.GREETING_COLOR.format(
        warna="merah"
    )


def test_scenario_f_audio_restart_while_speaking():
    s = drive(V.SPEAKING)
    s.handle(READY_AUDIO, 0.0)
    s.handle(AudioStatus(False, False, False, "WORKER_RESTART"), 4.5)
    actions = s.handle(READY_AUDIO, 6.0)
    assert actions[0] == ListenControl("auto", s.session_id) and s.state == V.READY
    # ready=True kedua tanpa ready=False di antaranya juga dianggap restart
    s = drive(V.GREETING)
    s.handle(READY_AUDIO, 0.0)
    s.handle(READY_AUDIO, 1.0)
    assert s.state == V.READY


def test_scenario_g_filtered_transcript_never_speaks():
    s = drive(V.LISTENING)
    for kind in ("min_speech", "no_speech"):
        actions = s.handle(transcript(s, "", False, kind), 3.0)
        assert not of(actions, Speak) and s.state == V.LISTENING
    s = drive(V.READY)  # di luar LISTENING juga tanpa Speak
    assert not of(s.handle(transcript(s, "", False, "no_speech"), 2.0), Speak)


def test_scenario_h_idle_timeout_by_tick():
    s = drive(V.READY)  # interaksi terakhir t=1
    assert s.handle(Tick(1.0 + IDLE_S), 1.0 + IDLE_S) == []  # belum melewati
    assert s.state == V.READY
    s.handle(SpeechStarted(s.session_id, 20.0), 20.0)  # interaksi menghitung ulang
    assert s.handle(Tick(1.0 + IDLE_S + 1), 1.0 + IDLE_S + 1) == []
    s.handle(Tick(20.0 + IDLE_S + 0.1), 20.0 + IDLE_S + 0.1)
    assert s.state == V.IDLE
    s = drive(V.READY, make(idle_reset_s=None))  # null = tidak pernah timeout
    assert s.handle(Tick(1e9), 1e9) == [] and s.state == V.READY


def test_scenario_i_regreet_cooldown():
    s = cooled()  # pergi di t=5
    assert names(s.handle(arrived(), 5.0 + COOLDOWN_S - 0.1)) == ("Ignored",)
    assert s.handle(arrived(), 5.0 + COOLDOWN_S)[0].text.startswith("Halo")
    s = drive(V.READY, make(regreet_cooldown_s=None))  # null = tanpa jeda
    s.handle(PersonLeft(1, 5.0, 4.0), 5.0)
    assert s.handle(arrived(), 5.0)[0].text.startswith("Halo")


def test_device_status_does_not_reset_session():
    s = drive(V.SPEAKING)
    sid = s.session_id
    (view,) = s.handle(CameraStatus(ok=False, message="kamera putus"), 4.5)
    assert not view.camera_ok and view.answer is not None
    (view,) = s.handle(AudioStatus(False, True, True, "MIC_DOWN"), 4.6)
    assert not view.mic_ok and view.answer is not None
    assert s.state == V.SPEAKING and s.session_id == sid and s.history
    assert s.handle(CameraStatus(ok=False, message="kamera putus"), 4.7) == []


def test_from_settings_reads_config():
    s = Session.from_settings(load_settings(ROOT / "config" / "dev.yaml"))
    assert s.fps_idle == 5 and s.fps_busy is None and s.idle_reset_s is None
    assert s.regreet_cooldown_s is None and s.min_majority is None


def test_typing_while_greeting_stops_greeting_and_ignores_late_done():
    s = drive(V.GREETING)
    greeting = s.greeting_uid
    actions = s.handle(TextSubmitted("Biaya kuliah berapa?"), 0.5)
    assert actions[0] == StopSpeaking(s.session_id)
    assert actions[1] == ListenControl("off", s.session_id)
    assert actions[3] == RunPipeline(s.session_id, "Biaya kuliah berapa?", (), "text")
    late = s.handle(SpeechDone(s.session_id, greeting, 0.2, interrupted=True), 0.6)
    assert names(late) == ("Ignored",) and s.state == V.THINKING


def test_typing_while_listening_ignores_late_transcript():
    s = drive(V.LISTENING)
    actions = s.handle(TextSubmitted("Jalur masuk apa saja?"), 2.5)
    assert actions[0] == ListenControl("off", s.session_id)
    late = s.handle(transcript(s), 3.0)
    assert names(late) == ("Ignored",) and s.state == V.THINKING and not of(late, Speak)


def test_transitions_markdown_export(tmp_path):
    import runpy

    md = transitions_markdown()
    assert md.count("\n| T") == 19 and md.count("\n| R0") == 6 and md.count("\n| D0") == 2
    out = tmp_path / "transitions.md"
    mod = runpy.run_path(str(ROOT / "scripts" / "session_table.py"))
    assert mod["main"](["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == md


# --- properti -----------------------------------------------------------------------------


@pytest.mark.parametrize("state", ALL)
@pytest.mark.parametrize("device", ["normal", "camera_down", "audio_down", "restarted"])
def test_person_left_from_any_state_ends_idle_with_empty_history(state, device):
    s = {"normal": at(state), "camera_down": camera_down(state),
         "audio_down": audio_down(state), "restarted": vision_restarted(state)}[device]()  # fmt: skip
    s.handle(PersonLeft(1, 50.0, 10.0), 50.0)
    assert s.state == V.IDLE and s.history == () and s.view.answer is None
    later = [a for a in s.handle(AnswerReady("s1", answer()), 51.0) if not isinstance(a, Ignored)]
    assert later == []
