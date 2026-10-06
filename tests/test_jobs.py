import pytest

from transliterator import jobs
from transliterator.jobs import RULES_VERSION, InvalidJob, run_job


def test_result_lines_up_with_the_texts_for_every_requested_script():
    result = run_job({"texts": ["ఓం శాంతిః", "", "శ్రీ"], "scripts": ["sa", "en"]})

    assert result == {
        "rulesVersion": RULES_VERSION,
        "scripts": {
            "sa": ["ॐ शांतिः", "", "श्री"],
            "en": ["oṃ śāntiḥ", "", "śrī"],
        },
    }


def test_an_empty_batch_is_fine():
    assert run_job({"texts": [], "scripts": ["sa"]})["scripts"] == {"sa": []}


def test_a_repeated_script_is_produced_once():
    assert list(run_job({"texts": ["ఓం"], "scripts": ["en", "sa", "en"]})["scripts"]) == [
        "en",
        "sa",
    ]


def test_spaced_nasal_flag_reaches_english_only():
    payload = {"texts": ["త్రినేత్రం భజే"], "scripts": ["en", "sa"], "spacedNasal": True}

    assert run_job(payload)["scripts"]["en"] == ["trinetram bhaje"]
    assert run_job(payload)["scripts"]["sa"] == ["त्रिनेत्रं भजे"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "texts",
        {"scripts": ["sa"]},
        {"texts": "ఓం", "scripts": ["sa"]},
        {"texts": ["ఓం", 3], "scripts": ["sa"]},
        {"texts": ["ఓం"]},
        {"texts": ["ఓం"], "scripts": []},
        {"texts": ["ఓం"], "scripts": "sa"},
        {"texts": ["ఓం"], "scripts": ["sa", "fr"]},
        {"texts": ["ఓం"], "scripts": ["te"]},  # the source script is not a target
        {"texts": ["ఓం"], "scripts": ["sa"], "spacedNasal": "yes"},
    ],
)
def test_invalid_payloads_are_rejected(payload):
    with pytest.raises(InvalidJob):
        run_job(payload)


def test_size_limits(monkeypatch):
    monkeypatch.setattr(jobs, "MAX_TEXTS", 2)
    with pytest.raises(InvalidJob, match="too many texts"):
        run_job({"texts": ["a", "b", "c"], "scripts": ["sa"]})

    monkeypatch.setattr(jobs, "MAX_CHARS", 5)
    with pytest.raises(InvalidJob, match="exceed"):
        run_job({"texts": ["abcdef"], "scripts": ["sa"]})
