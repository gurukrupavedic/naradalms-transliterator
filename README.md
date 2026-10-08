# Transliterator

A BullMQ worker that turns Telugu chant text into other scripts: Devanagari (`sa`), IAST (`en`), Kannada (`kn`) and Tamil (`ta`). It uses [Aksharamukha](https://github.com/virtualvinodh/aksharamukha) 2.3, which is Python, so this is its own small service. It needs Redis and nothing else: no database, no object storage, no HTTP port.

This service lives in its own repository because Aksharamukha is AGPL-3.0; it is licensed AGPL-3.0 as well (see [LICENSE](LICENSE)). It is used by [NaradaLMS](https://github.com/gurukrupavedic/NaradaLMS), which talks to it only through the queue described below, with plain JSON in and out. Paths such as `apps/api/...` in this README refer to that repository.

Telugu is the only script anyone writes. The API sends verses here and stores what comes back, so a new script or a corrected rule never means re-importing a document.

## The `transliterate` queue

The API adds jobs to the queue named `transliterate`.

```jsonc
// job data
{ "texts": ["ఓం శాంతిః", "సంకల్ప"], "scripts": ["sa", "en"], "spacedNasal": false }

// return value: each script's list lines up index-for-index with `texts`
{ "rulesVersion": 1, "scripts": { "sa": ["ॐ शांतिः", "संकल्प"], "en": ["oṃ śāntiḥ", "saṅkalpa"] } }
```

- `scripts` is any of `sa`, `en`, `kn`, `ta`. `texts` is one batch, normally a heading's verses.
- `spacedNasal` (optional, `en` only) also rewrites ṃ across spaces and Vedic accents: "trinetraṃ bhaje" becomes "trinetram bhaje". It is off by default because it also rewrites Telugu prose written in IAST.
- `rulesVersion` is bumped in `src/transliterator/jobs.py` whenever the output for the same input can change. Store it next to derived text so stale rows can be found and rebuilt.
- A payload that can never succeed (unknown script, wrong types, more than 5,000 texts or 1,000,000 characters) fails immediately without retrying. Anything else follows the job's own retry settings.

The exact options per script, and why, are in `src/transliterator/scripts.py`.

### Is a worker listening?

While it runs, a worker refreshes the key `<prefix>:transliterate:heartbeat` every 5 seconds with a 15-second expiry; the value is its `rulesVersion`. A producer that finds the key missing knows no worker is up and can fail at once instead of waiting out a job timeout. This is separate from BullMQ's own worker listing on purpose: Node's `Queue.getWorkers()` looks for client names with the queue name base64-encoded, the Python library registers the plain name, so it never sees this worker. The API client reads the same key (`workerHeartbeatKey` in NaradaLMS's `apps/api/src/transliteration/queue.ts`), and a contract test starts the real worker to keep the two in agreement.

## Adding a script

1. Add a `Target` for it in `src/transliterator/scripts.py`, with golden tests in `tests/test_scripts.py`.
2. In NaradaLMS, add the value to the `script` enum in `packages/db/src/schema/school.ts` and generate a migration.
3. In NaradaLMS, add it to `DERIVED_SCRIPTS` (`apps/api/src/docChapters/schema.ts`) and to `transliterationScriptSchema` (`apps/api/src/transliteration/schema.ts`).
4. In NaradaLMS, give the web app a font and a label for it (`apps/web/app/layout.tsx`, the `SCRIPTS` lists).
5. Deploy the worker first, then the API. The two are deployed from different repositories now, so keep queue payload changes backward-compatible (add fields; don't rename or remove them).

Content that already exists catches up by itself: on every boot the API finds each segment and doc chapter title that lacks a script in `DERIVED_SCRIPTS` and derives it from the Telugu (NaradaLMS's `apps/api/src/docChapters/backfill.ts`). It only adds rows, never rewrites one, and when nothing is missing it does almost no work. If the worker isn't up yet, the job retries for about twenty minutes.

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
uv sync
REDIS_URL=redis://localhost:6379 uv run transliterator
```

A worker needs about 40 MiB at rest and handles a batch of verses in a few milliseconds.

## Deploying

The worker is its own Railway service in each environment, with one variable and no port or public domain:

| Environment | Service name | `REDIS_URL` |
|---|---|---|
| staging | `transliterator` | `${{Redis-5ouG.REDIS_URL}}` |
| production | `transliterator-prod` | `${{Redis.REDIS_URL}}` |

Service names are unique per Railway project, which is why the two differ. `REDIS_URL` is a reference to that environment's own Redis service, the same one its API uses, so no secret is copied anywhere. The queue name and key prefix are the defaults on both sides.

Deploys are done by two workflows in this repository (`railway up` uploads the checkout, so the Railway services aren't linked to a GitHub repo):

- **Staging** (`deploy-staging.yml`) runs after every green CI on `main`, like the API's. It then polls the API's `GET /v1/health/transliterator` when the `STAGING_API_URL` variable is set until it answers 200, which it does only while a worker's heartbeat key is alive. A runner can't reach Redis on Railway's private network, so the API does the looking.
- **Production** (`deploy-production.yml`) is manual: type `deploy` to confirm. Set the `PRODUCTION_API_URL` variable on the production environment to make it run the same check.

Each environment (`staging`, `production`) needs a `RAILWAY_TOKEN` secret (a Railway project token for that environment) in this repository's settings.

Setting up a new environment, or rebuilding one, by hand:

```sh
railway environment <env>
railway add --service <service-name>
railway variable set 'REDIS_URL=${{<redis-service-name>.REDIS_URL}}' --service <service-name> --environment <env> --skip-deploys
railway up --service <service-name> --environment <env> --ci
railway logs --service <service-name> --environment <env> --lines 20    # look for "transliterator ready"
```

The API's `/v1/health/transliterator` is deliberately separate from `/v1/health/ready`: readers are served without the worker, so a worker that is down must not take the API out of rotation.

## Tests

```sh
uv run ruff check . && uv run ruff format --check .
REDIS_URL=redis://localhost:6379 uv run pytest
```

Without `REDIS_URL` the two end-to-end tests (a real producer, the real worker, a real Redis) are skipped; everything else runs. Each end-to-end run uses its own key prefix and removes it afterwards.

The golden tests pin Aksharamukha's current output for a handful of public-domain verses. They guard against drift when the library or the options change; they are not an independent check of the transliteration itself. If you bump `aksharamukha` in `pyproject.toml` and a golden test moves, decide whether the new text is right, then bump `RULES_VERSION`.

## Upgrading and constraints

- Python is pinned to 3.13 or earlier: Aksharamukha 2.3 imports `ast.Str`, which Python 3.14 removed.
- `uv.lock` is committed and the image installs with `--locked`, so a rebuild never picks up new versions on its own.
- Aksharamukha is AGPL-3.0, like this repository.

## License

AGPL-3.0-only; see [LICENSE](LICENSE). This follows from the dependency on [Aksharamukha](https://github.com/virtualvinodh/aksharamukha), which declares AGPL-3.0 in its package metadata and README. If you run a modified version as a network service, section 13 of the license requires you to offer its source to the people using it.
