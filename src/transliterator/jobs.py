"""The `transliterate` job: payload validation and the batch itself, with no queue in sight.

Payload:  {"texts": [str, ...], "scripts": ["sa", "en", "kn"], "spacedNasal": false}
Result:   {"rulesVersion": 1, "scripts": {"sa": [str, ...], "en": [str, ...], ...}}

Each script's list lines up index-for-index with `texts`, so a caller sends one heading's verses in
a single job and zips the answer back. The worker never touches the database: it takes text in and
returns text out, so tenancy and storage stay in the API.
"""

from typing import Any

from .scripts import TARGETS, transliterate

# Bump whenever the output for the same input can change (a new Aksharamukha version, different
# options, a changed post-processing rule). The API stores it beside derived text so a stale batch
# can be found and rebuilt.
RULES_VERSION = 1

# A chapter has a few hundred verses at most; these only stop a malformed or runaway payload from
# blocking the worker.
MAX_TEXTS = 5_000
MAX_CHARS = 1_000_000


class InvalidJob(ValueError):
    """The payload can never succeed, so retrying it is pointless."""


def _validated(data: Any) -> tuple[list[str], list[str], bool]:
    if not isinstance(data, dict):
        raise InvalidJob("payload must be an object")

    texts = data.get("texts")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise InvalidJob("texts must be a list of strings")
    if len(texts) > MAX_TEXTS:
        raise InvalidJob(f"too many texts: {len(texts)} (max {MAX_TEXTS})")
    if sum(len(t) for t in texts) > MAX_CHARS:
        raise InvalidJob(f"texts exceed {MAX_CHARS} characters")

    scripts = data.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise InvalidJob("scripts must be a non-empty list")
    unknown = [s for s in scripts if s not in TARGETS]
    if unknown:
        raise InvalidJob(f"unknown scripts: {', '.join(map(str, unknown))}")

    spaced = data.get("spacedNasal", False)
    if not isinstance(spaced, bool):
        raise InvalidJob("spacedNasal must be a boolean")

    return texts, list(dict.fromkeys(scripts)), spaced


def run_job(data: Any) -> dict[str, Any]:
    texts, scripts, spaced = _validated(data)
    return {
        "rulesVersion": RULES_VERSION,
        "scripts": {
            script: [transliterate(t, script, spaced_nasal_rule=spaced) for t in texts]
            for script in scripts
        },
    }
