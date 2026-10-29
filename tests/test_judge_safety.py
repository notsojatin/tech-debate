import pytest

from app.judge import JudgeOut, SideScores, combine, render_for_judge
from app.safety import TopicRejected, check_topic, denylist_hits
from app.state import DebateState, Phase, Turn


def s(n):
    return SideScores(evidence_use=n, rebuttal_responsiveness=n, argument_quality=n, stayed_on_side=n)


def test_combine_maps_swapped_runs():
    # Run 1: pro is A and wins; run 2: con is A, pro is B, pro wins again.
    r1 = JudgeOut(a=s(8), b=s(5), winner="a", reason="Side A cited more than side B")
    r2 = JudgeOut(a=s(6), b=s(7), winner="b", reason="pro answered rebuttals")
    out = combine(r1, r2)
    assert out["totals"] == {"pro": 30.0, "con": 22.0}
    assert out["winner"] == "pro"
    assert out["position_consistent"] is True
    assert out["runs"][0]["reason"] == "Pro cited more than Con"


def test_combine_detects_position_bias_and_ties():
    # Judge always picks whoever is A: position bias, and averages cancel to a tie.
    out = combine(JudgeOut(a=s(8), b=s(6), winner="a", reason="r1"),
                  JudgeOut(a=s(8), b=s(6), winner="a", reason="r2"))
    assert out["position_consistent"] is False
    assert out["winner"] == "tie"


def test_clamps_scores():
    out = combine(JudgeOut(a=s(15), b=s(-3), winner="a", reason=""), JudgeOut(a=s(0), b=s(10), winner="b", reason=""))
    assert out["average"]["pro"]["evidence_use"] == 10


def test_render_for_judge_anonymises_and_orders(tmp_path):
    st = DebateState(topic="T", run_dir=tmp_path, models={"pro": "p", "con": "c", "judge": "j"})
    st.turns = [Turn(phase=Phase.OPENINGS, side="pro", model="p", text="PRO TEXT"),
                Turn(phase=Phase.OPENINGS, side="con", model="c", text="CON TEXT")]
    a = render_for_judge(st, "pro")
    b = render_for_judge(st, "con")
    assert a.index("PRO TEXT") < a.index("CON TEXT")
    assert b.index("CON TEXT") < b.index("PRO TEXT")
    assert "qwen" not in a and " p " not in a


@pytest.mark.parametrize("topic", ["Should we ban abortion", "Trump vs Biden on AI", "Islam vs Christianity"])
def test_denylist_blocks(cfg, topic):
    with pytest.raises(TopicRejected):
        check_topic(topic, cfg, llm=None)


@pytest.mark.parametrize("topic", ["Race conditions are the worst bug class", "God objects are fine",
                                   "Rust is better than Go for CLIs"])
def test_denylist_allows_tech(topic):
    from app.config import load_yaml
    assert denylist_hits(topic, load_yaml("topic_filter.yaml")["deny"]) == []
