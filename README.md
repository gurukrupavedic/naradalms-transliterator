# Transliterator

A BullMQ worker that turns Telugu chant text into other scripts: Devanagari (`sa`), IAST (`en`) and Kannada (`kn`). It uses [Aksharamukha](https://github.com/virtualvinodh/aksharamukha) 2.3, which is Python, so this is its own small service. It needs Redis and nothing else: no database, no object storage, no HTTP port.

Telugu is the only script anyone writes. The API sends verses here and stores what comes back, so a new script or a corrected rule never means re-importing a document.

## The `transliterate` queue

The API adds jobs to the queue named `transliterate`.

```jsonc
// job data
{ "texts": ["ఓం శాంతిః", "సంకల్ప"], "scripts": ["sa", "en"], "spacedNasal": false }

// return value: each script's list lines up index-for-index with `texts`
{ "rulesVersion": 1, "scripts": { "sa": ["ॐ शांतिः", "संकल्प"], "en": ["oṃ śāntiḥ", "saṅkalpa"] } }
```

- `scripts` is any of `sa`, `en`, `kn`. `texts` is one batch, normally a heading's verses.
- `spacedNasal` (optional, `en` only) also rewrites ṃ across spaces and Vedic accents: "trinetraṃ bhaje" becomes "trinetram bhaje". It is off by default because it also rewrites Telugu prose written in IAST.
- `rulesVersion` is bumped in `src/transliterator/jobs.py` whenever the output for the same input can change. Store it next to derived text so stale rows can be found and rebuilt.
- A payload that can never succeed (unknown script, wrong types, more than 5,000 texts or 1,000,000 characters) fails immediately without retrying. Anything else follows the job's own retry settings.

The exact options per script, and why, are in `src/transliterator/scripts.py`.

## Running it

Configuration is environment variables:

| Variable | Default | |
|---|---|---|
| `REDIS_URL` | required | The same Redis the API uses |
| `QUEUE_PREFIX` | `bull` | BullMQ key prefix; leave it unless the API's queues use another |
| `LOG_LEVEL` | `INFO` | |

With the rest of the stack (Redis comes from the same compose file):

```sh
docker compose up -d narada-transliterator
docker logs narada-transliterator -f
```

Or directly, with [uv](https://docs.astral.sh/uv/):

```sh
cd apps/transliterator
uv sync
REDIS_URL=redis://localhost:6379 uv run transliterator
```

A worker needs about 40 MiB at rest and handles a batch of verses in a few milliseconds.

## Tests

```sh
cd apps/transliterator
uv run ruff check . && uv run ruff format --check .
REDIS_URL=redis://localhost:6379 uv run pytest
```

Without `REDIS_URL` the two end-to-end tests (a real producer, the real worker, a real Redis) are skipped; everything else runs. Each end-to-end run uses its own key prefix and removes it afterwards.

The golden tests pin Aksharamukha's current output for a handful of public-domain verses. They guard against drift when the library or the options change; they are not an independent check of the transliteration itself. If you bump `aksharamukha` in `pyproject.toml` and a golden test moves, decide whether the new text is right, then bump `RULES_VERSION`.

## Upgrading and constraints

- Python is pinned to 3.13 or earlier: Aksharamukha 2.3 imports `ast.Str`, which Python 3.14 removed.
- `uv.lock` is committed and the image installs with `--locked`, so a rebuild never picks up new versions on its own.
- Aksharamukha is AGPL-3.0, like this repository.
