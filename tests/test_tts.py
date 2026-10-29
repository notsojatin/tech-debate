from app.render import _ts, spoken_model
from app.tools.tts import Pronunciation, clean_for_speech, split_sentences


def test_cleanup_strips_markup_cites_urls():
    pron = Pronunciation()
    raw = "**K8s** scales well [E3] (E4, E5) see https://x.io/a and [docs](https://y.com). <think>hmm</think>"
    out = clean_for_speech(raw, pron)
    assert "Kubernetes" in out
    for bad in ("E3", "E4", "http", "*", "[", "think", "hmm"):
        assert bad not in out
    assert "docs" in out


def test_strips_tags_and_numeric_refs():
    pron = Pronunciation()
    assert clean_for_speech("A limited snapshot. <evidence id=", pron) == "A limited snapshot."
    assert clean_for_speech("Proven stability benefits [1].", pron) == "Proven stability benefits."
    assert clean_for_speech("Latency < 10ms wins", pron) == "Latency less than 10 milliseconds wins"
    assert clean_for_speech("not inherent tooling maturity <.", pron) == "not inherent tooling maturity."
    assert clean_for_speech("A 9.5x gain on 16 GB.", pron) == "A 9.5 times gain on 16 gigabytes."


def test_acronyms():
    pron = Pronunciation()
    assert clean_for_speech("SQS beats Kafka on AWS.", pron) == "S-Q-S beats Kafka on A-W-S."
    assert clean_for_speech("Use CI/CD with NASA RAM.", pron) == "Use C-I C-D with NASA RAM."
    assert clean_for_speech("Spin up a VPC and IAM.", pron) == "Spin up a V-P-C and I-A-M."
    assert clean_for_speech("This is NOT fine.", pron) == "This is not fine."


def test_sentences():
    assert split_sentences("One thing. Two things! 3 things? done") == ["One thing.", "Two things!", "3 things? done"]


def test_srt_timestamp_and_model_names():
    assert _ts(3_723_456) == "01:02:03,456"
    assert spoken_model("qwen3:4b") == "Qwen 3, 4 billion"
    assert spoken_model("llama3.2:3b") == "Llama 3.2, 3 billion"
    assert spoken_model("gemma3:4b") == "Gemma 3, 4 billion"
