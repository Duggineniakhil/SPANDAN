"""The eval harnesses themselves (M2-38, M2-39), with fake models: the checks must catch what they claim to."""
from app.evals.agent_eval import incidents, run
from tests.test_agent import FakeProvider, good_script


def careful_script():
    """good_script, but it stops (like a real model) when a tool says there is no part or slot."""
    gen = good_script()
    results = None
    try:
        while True:
            turn = gen.send(results) if results is not None else next(gen)
            results = yield turn
            if any(r.is_error for r in results or []):
                return
    except (KeyError, IndexError, StopIteration):
        return


def fake():
    return [FakeProvider("fake", careful_script)]


def test_agent_eval_scores_a_good_plan_and_correct_refusals():
    rs = {r.id: r for r in run({1, 9, 11, 17, 19}, pause=0, providers=fake(), log=lambda s: None)}
    assert rs[1].passed and rs[1].checks["cheapest_part"] and rs[1].checks["earliest_slot"], rs[1]
    assert rs[19].passed  # big budget: still the cheapest
    for i in (9, 11, 17):  # no valid plan exists: refusing is the right answer
        assert rs[i].expected == "no plan" and rs[i].outcome == "no plan" and rs[i].passed, rs[i]
        assert rs[i].checks["owner_told"] and rs[i].checks["safety"]


def test_agent_eval_catches_a_wrong_choice():
    # good_script orders a 6205 bearing for a machine with a 6204 one: wrong part, and not "planned" as expected
    r = run({4}, pause=0, providers=fake(), log=lambda s: None)[0]
    assert not r.passed


class RateLimited:
    """Every call fails like a free tier that is out of quota."""
    name = "limited"

    def start(self, *a):
        from app.agent.llm import ProviderError
        raise ProviderError("Gemini API error: 429 RESOURCE_EXHAUSTED")


def test_no_llm_available_is_not_scored_as_an_agent_failure(tmp_path):
    rs = run({1}, pause=0, providers=[RateLimited()], log=lambda s: None, retry_waits=(0,), out=tmp_path)
    assert not rs[0].scored and not rs[0].passed and "not scored" in rs[0].notes[0]
    import json
    rep = json.loads((tmp_path / "agent_eval_report.json").read_text(encoding="utf-8"))
    assert rep["scored"] == 0 and rep["not_scored"] == [1]


def test_model_giving_up_is_scored_even_if_the_fallback_is_rate_limited():
    def gives_up():
        yield from ()
    r = run({1}, pause=0, providers=[FakeProvider("fake", gives_up), RateLimited()], log=lambda s: None,
            retry_waits=(0,))[0]
    assert r.scored and not r.passed


def test_twenty_incidents():
    assert [i.id for i in incidents()] == list(range(1, 21))


# ---------- voice eval ----------

def test_voice_eval_scores_and_flags_false_approvals(tmp_path):
    from app.evals.voice_eval import add_noise, clips, evaluate
    from tests.test_voice import FakeVoice, IntentLLM, tone_wav

    heard = {"kn_yes_s01.wav": "ಹೌದು", "kn_no_s01.ogg": "ಬೇಡ", "hi_yes_s02.wav": "हाँ जी",
             "hi_no_s02_noisy.wav": "हाँ",  # misheard "no" as "yes": a false approval
             "kn_question_s03.wav": "ಹೌದು ಆದರೆ ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ ಬರಲಿ", "notes.txt": None, "bad_name.wav": None}
    for name in heard:
        (tmp_path / name).write_bytes(tone_wav(1.0))
    assert [c[0].name for c in clips(tmp_path)] == sorted(n for n, t in heard.items() if t)

    class ByFile(FakeVoice):
        def stt(self, audio, lang, filename="x.wav"):
            from app.voice.provider import Transcript
            return Transcript(heard[filename])

    rep = evaluate(tmp_path, provider=ByFile(), llm_providers=[IntentLLM("question", "Monday morning")], log=lambda s: None)
    assert rep["yes_no"] == {"n": 4, "correct": 3, "accuracy": 0.75}
    assert rep["false_approvals"] == ["hi_no_s02_noisy.wav"]
    assert rep["by_group"]["noisy"]["correct"] == 0 and rep["by_group"]["kn"]["accuracy"] == 1.0
    assert rep["requests"] == {"n": 1, "correct": 1, "accuracy": 1.0}
    noisy = add_noise(tone_wav(1.0), snr_db=10, seed=1)
    assert len(noisy) == len(tone_wav(1.0)) and noisy != tone_wav(1.0)
