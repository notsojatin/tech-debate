from app.agents import (OpeningOut, RebuttalOut, has_concession, jaccard, quote_matches, truncate_words,
                        validate_turn)
from app.ledger import Ledger, normalize_cite
from app.state import Phase


def ledger():
    lg = Ledger()
    lg.add("pro", "q", "https://a.com/x", "A", "snippet one about monorepos")
    lg.add("con", "q", "https://b.com/y", "B", "snippet two about polyrepos")
    return lg


def test_unknown_and_missing_cites(cfg):
    out = OpeningOut(text="Monorepos win.", cites=["E9"], new_point="Atomic changes")
    errs = validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=ledger(), own_points=[], opponent_text=None).errors
    assert any("do not exist" in e for e in errs)
    assert any("empty" in e for e in errs)


def test_valid_opening_passes(cfg):
    out = OpeningOut(text="Monorepos make atomic changes easy.", cites=["[E1]"], new_point="Atomic changes")
    check = validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=ledger(), own_points=[], opponent_text=None)
    assert check.errors == []


def test_no_cites_needed_without_evidence(cfg):
    out = OpeningOut(text="Monorepos win.", cites=[], new_point="x")
    assert validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=Ledger(), own_points=[],
                         opponent_text=None).errors == []


def test_word_limit_and_urls(cfg):
    out = OpeningOut(text="word " * 200 + "see https://evil.com", cites=["E1"], new_point="x")
    errs = validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=ledger(), own_points=[], opponent_text=None).errors
    assert any("limit" in e for e in errs)
    assert any("URL" in e for e in errs)


def test_markup_rejected_and_stripped(cfg):
    from app.agents import strip_markup
    out = OpeningOut(text="Monorepos win [1]. See E1 and <evidence id=", cites=["E1"], new_point="x")
    errs = validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=ledger(), own_points=[], opponent_text=None).errors
    assert any("markup" in e for e in errs)
    assert strip_markup(out.text) == "Monorepos win. See and"


def test_inline_cites_repaired_without_retry(cfg):
    from app.agents import repair_inline_cites
    out = OpeningOut(text="Builds got faster (E2) and **cheaper** [1].", cites=["E1"], new_point="x")
    repair_inline_cites(out)
    assert out.text == "Builds got faster and cheaper."
    assert out.cites == ["E1", "E2"]
    assert validate_turn(out, phase=Phase.OPENINGS, cfg=cfg, ledger=ledger(), own_points=[],
                         opponent_text=None).errors == []


def test_bare_and_dashed_ids_leave_no_gaps():
    from app.agents import repair_inline_cites
    cases = {
        "Analyses like E5 reveal it is cheap.": "Analyses like one source reveal it is cheap.",
        "As detailed in E14 and E15, fees are small.": "As detailed in these sources, fees are small.",
        "Numerous case studies – E12, E13 – show wide adoption.": "Numerous case studies show wide adoption.",
        "Fees are small (E2, E3).": "Fees are small.",
    }
    for raw, want in cases.items():
        out = OpeningOut(text=raw, cites=[], new_point="x")
        repair_inline_cites(out)
        assert out.text == want, raw
        assert out.cites  # IDs were moved into cites


def test_counter_claim():
    from app.agents import counter_claim
    assert counter_claim("Kubernetes is overkill for most startups") == "Kubernetes is not overkill for most startups"
    assert counter_claim("Rust is better than Go for CLIs.") == "Rust is not better than Go for CLIs"
    assert counter_claim("Microservices should be avoided by small teams") == \
        "Microservices should not be avoided by small teams"
    assert counter_claim("ORMs are not worth it") == "ORMs are worth it"
    assert counter_claim("Startups need Kubernetes") == "It is not true that Startups need Kubernetes"


def test_stance_check_uses_explicit_claims(cfg, tmp_path):
    from app.agents import StanceOut, stance_check
    from app.state import DebateState

    class Classifier:
        def __init__(self, answer):
            self.answer, self.prompt = answer, ""

        def structured(self, model, system, user, schema):
            self.prompt = user
            return StanceOut(reason="r", supports=self.answer)

    st = DebateState(topic="Kubernetes is overkill for most startups", run_dir=tmp_path,
                     models={}, counter_claim="Kubernetes is not overkill for most startups")
    clf = Classifier("claim_2")
    err = stance_check(clf, cfg, st, "pro", "Startups do not need Kubernetes.")
    assert 'Claim 2: "Kubernetes is not overkill for most startups"' in clf.prompt
    assert err and "stance check:" in err
    assert stance_check(Classifier("claim_1"), cfg, st, "pro", "t") is None
    assert stance_check(Classifier("both"), cfg, st, "pro", "t") is None
    assert stance_check(Classifier("claim_1"), cfg, st, "con", "t") is not None


def test_quote_matching():
    src = "Polyrepos let teams ship independently. They also isolate failures."
    assert quote_matches("Polyrepos let teams ship independently", src, 0.85)
    assert quote_matches("polyrepos let team ship independently", src, 0.85)  # near-verbatim
    assert not quote_matches("Monorepos are always slower to build", src, 0.85)
    assert not quote_matches("ok", src, 0.85)


def test_rebuttal_quote_and_repeat(cfg):
    out = RebuttalOut(quote="something they never said", attacks="x", text="No.", cites=["E1"],
                      new_point="Atomic cross-project changes")
    check = validate_turn(out, phase=Phase.REBUTTAL_1, cfg=cfg, ledger=ledger(),
                          own_points=["atomic cross-project changes are easy"], opponent_text="Polyrepos isolate failures.")
    assert check.quote_matched is False
    assert any("word-for-word" in e for e in check.errors)
    assert any("repeats" in e for e in check.errors)


def test_concessions():
    assert has_concession("I agree that build times matter.")
    assert has_concession("You're right about tooling, but")
    assert has_concession("That's a fair point.")
    assert not has_concession("My opponent is wrong about tooling.")


def test_helpers():
    assert normalize_cite("(e12)") == "E12"
    assert jaccard("atomic changes across services", "atomic changes across services") == 1.0
    assert truncate_words("One two three. Four five six seven.", 5) == "One two three."
