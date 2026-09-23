"""Phase G: language routing across two ASR backends.

`BLOCKERS.md` O16 exists because no model VIVE can use covers all three
priority languages. The router's job is to send each language to the backend
measured to handle it and to decline the rest - and the ways that can go wrong
are worth pinning, because each one degrades silently:

  * routing a language to a backend that does not cover it produces a
    confident wrong transcript, which feeds the intent head and becomes risk;
  * treating an uncovered language as an ERROR tells an operator the model
    broke when in fact the product never supported that language;
  * one backend failing to load taking the others down turns a missing English
    model into a total ASR outage;
  * losing the backend's `model_version` makes a packet's evidence
    unattributable once two models are in play.

These run WITHOUT the ML extras, with fake backends, because routing is
dispatch logic and must be verifiable on a machine with no checkpoints. The
real Whisper adapter's own unconfigured path is checked at the end.
"""

from __future__ import annotations

import struct

from app.adapters.interfaces import AdapterInfo, AsrResult, AudioWindow
from app.adapters.real.asr_router import RoutingAsrAdapter
from app.adapters.real.asr_whisper import WhisperAsrAdapter
from app.schemas.models import AdapterMode, AnalyzerStatus

SAMPLE_RATE = 16_000


def window(language: str | None = None, **kw) -> AudioWindow:
    n = SAMPLE_RATE * 2
    base = dict(session_id="s-1", seq=1, start_sec=0.0, end_sec=2.0,
                pcm=struct.pack(f"<{n}h", *([1000] * n)),
                sample_rate=SAMPLE_RATE)
    base.update(kw)
    field = AudioWindow(**base)
    if language is not None:
        object.__setattr__(field, "language", language)
    return field


class FakeAsr:
    """A backend that transcribes only the languages it declares."""

    adapter_key = "asr"
    mode = AdapterMode.REAL

    def __init__(self, model_id: str, languages, *, loads: bool = True) -> None:
        self.id = model_id
        self.version = f"{model_id}-v1"
        self._languages = tuple(languages)
        self._loads = loads
        self._status = AnalyzerStatus.UNAVAILABLE
        self.calls: list[str | None] = []
        self.default = ""

    def load(self):
        self._status = (AnalyzerStatus.AVAILABLE if self._loads
                        else AnalyzerStatus.LOAD_ERROR)
        return self._status

    def available(self):
        return self._status is AnalyzerStatus.AVAILABLE

    @property
    def languages(self):
        return self._languages if self.available() else ()

    def set_default_language(self, lang):
        self.default = lang

    def describe(self):
        return AdapterInfo(
            adapter_key="asr", model_id=self.id, model_version=self.version,
            mode=self.mode, status=self._status, revision=f"fake/{self.id}",
            languages=self.languages, execution_provider="fake",
            sample_rate=SAMPLE_RATE, detail=None)

    def analyze(self, win):
        language = getattr(win, "language", None) or self.default
        self.calls.append(language)
        return AsrResult(status=AnalyzerStatus.AVAILABLE,
                         model_version=self.version, mode=self.mode,
                         transcript=f"{self.id}:{language}", confidence=0.5,
                         language=language)


def build(**kw):
    indic = FakeAsr("indic", ("hi", "ta"), **kw.pop("indic", {}))
    english = FakeAsr("whisper", ("en",), **kw.pop("english", {}))
    router = RoutingAsrAdapter(indic, english)
    router.load()
    router.set_default_language(kw.pop("default", "hi"))
    return router, indic, english


def test_each_language_reaches_the_backend_that_covers_it():
    router, indic, english = build()

    assert router.analyze(window("hi")).transcript == "indic:hi"
    assert router.analyze(window("ta")).transcript == "indic:ta"
    assert router.analyze(window("en")).transcript == "whisper:en"

    # The crucial negative: English never reached the Indic model, which has
    # no English mask and would otherwise emit Indic tokens for English audio.
    assert "en" not in indic.calls
    assert english.calls == ["en"]


def test_the_packet_names_the_model_that_transcribed_it():
    """Evidence must stay attributable once two models are in play."""
    router, _indic, _english = build()

    assert router.analyze(window("hi")).model_version == "indic-v1"
    assert router.analyze(window("en")).model_version == "whisper-v1"


def test_an_uncovered_language_is_unsupported_not_an_error():
    router, _indic, _english = build()

    result = router.analyze(window("fr"))
    assert result.status is AnalyzerStatus.UNSUPPORTED_LANGUAGE
    assert result.transcript is None
    # Not INFERENCE_ERROR: no model failed. The product does not cover French,
    # and the UI renders these two statuses very differently.
    assert result.status is not AnalyzerStatus.INFERENCE_ERROR


def test_a_window_with_no_language_uses_the_session_default():
    router, indic, english = build(default="hi")

    assert router.analyze(window(None)).transcript == "indic:hi"
    assert english.calls == []


def test_the_default_language_is_pushed_into_every_backend():
    """The router and its backends must resolve the language identically.

    If they disagree, a window routed to a backend on the router's reading can
    be refused by that same backend on its own reading, and the packet reports
    UNSUPPORTED_LANGUAGE for a language that is in fact covered.
    """
    router, indic, english = build(default="en")

    assert indic.default == "en"
    assert english.default == "en"
    assert router.analyze(window(None)).transcript == "whisper:en"


def test_one_backend_failing_to_load_does_not_disable_the_other():
    router, _indic, english = build(english={"loads": False})

    assert router.available()
    assert router.languages == ("hi", "ta")
    assert router.analyze(window("hi")).status is AnalyzerStatus.AVAILABLE
    # English is now uncovered, so it degrades to unsupported rather than
    # taking Hindi down with it.
    assert router.analyze(window("en")).status is AnalyzerStatus.UNSUPPORTED_LANGUAGE
    assert english.calls == []


def test_no_backend_loading_leaves_the_router_unavailable():
    router, _indic, _english = build(indic={"loads": False},
                                     english={"loads": False})

    assert not router.available()
    assert router.languages == ()
    assert router.describe().status is not AnalyzerStatus.AVAILABLE


def test_describe_reports_the_union_and_names_each_backend():
    router, _indic, _english = build()
    info = router.describe()

    assert info.languages == ("en", "hi", "ta")
    assert info.mode is AdapterMode.REAL
    assert "indic[hi,ta]=AVAILABLE" in (info.detail or "")
    assert "whisper[en]=AVAILABLE" in (info.detail or "")


def test_unconfigured_whisper_is_unavailable_not_a_load_error():
    """An empty model dir means English is off, which is not a failure."""
    adapter = WhisperAsrAdapter("")

    assert adapter.load() is AnalyzerStatus.UNAVAILABLE
    assert adapter.describe().status is AnalyzerStatus.UNAVAILABLE
    assert adapter.languages == ()
    # Still REAL. A real adapter that did not load never reports itself as
    # mock (docs/ML_SPEC.md 4).
    assert adapter.describe().mode is AdapterMode.REAL


def test_whisper_declares_english_only():
    """Phase 10A measured WER 1.1640 on Hindi and 0.9084 on Tamil.

    Registering those languages would replace a good IndicConformer transcript
    with a bad one while looking like a coverage improvement.
    """
    from app.adapters.real.asr_whisper import DEFAULT_LANGUAGES

    assert DEFAULT_LANGUAGES == ("en",)


def test_a_router_with_no_backends_declines_everything():
    router = RoutingAsrAdapter()
    router.load()

    assert not router.available()
    assert router.analyze(window("hi")).status is AnalyzerStatus.UNSUPPORTED_LANGUAGE
