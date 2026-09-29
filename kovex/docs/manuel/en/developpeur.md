# Developer manual

## Architecture

```
src/
  api/          HTTP endpoints (FastAPI), access policy, schemas
  core/
    data/       CSV loading, matrix building, quality
    mining/     Role discovery and threshold exploration algorithms
    knowledge/  Knowledge base: approved and rejected roles, exclusions
    audit/      Chained audit trail
    security/   Authentication, passwords, rate limiting
    workspaces/ Isolation by client or environment
  infrastructure/ Logging, server-side i18n, product identity
frontend/       Web application with no external dependency
tests/          pytest suite, including tests/ihm for the browser
docs/           Documentation, including docs/manuel served by the application
```

One rule runs through the whole code base: **the server never builds a
displayed label**. It returns a code and its parameters; the client
translates. A server does not know its user's language.

## Conventions

**No hardcoded value.** Thresholds, paths, column names: everything comes from
the configuration. A value written into the code is a defect, not a shortcut.

**No presupposed column name.** Client files have the columns they have. Only
the configuration links them to internal identifiers.

**Default deny.** Every route must be declared in
`src/api/security_policy.py`. An undeclared route is refused, and a test
checks this across every route of the application.

**Comments explain the why.** A comment that paraphrases the code is noise. A
comment that says which defect the line avoids is still valuable years later.

## Tests

```
python -m venv .venv                    # a dedicated environment: the lock
.venv\Scripts\activate                  # only holds if it alone decides
pip install -r requirements-dev.txt     # inherits the lock, not the bounds
python -m playwright install chromium   # once, downloads the browser

python -m pytest                        # everything
python -m pytest tests/ihm              # browser
python -m pytest --cov --cov-report=term-missing   # backend coverage
python couverture_frontend.py           # JavaScript coverage
```

Without Playwright, the interface tests are **skipped silently**:
`tests/ihm/conftest.py` passes its import to `pytest.importorskip`. The
campaign passes, without half of what it claims to check, and frontend
coverage measures nothing. `python -m playwright install chromium` needs
network access; on an isolated machine, fetch the browser elsewhere and point
`PLAYWRIGHT_BROWSERS_PATH` at it. None of this concerns the delivered product:
Playwright only serves to test it.

Three families:

- **unit and integration**: the majority, on generated data sets — never on
  client data, so they run on a bare machine.
- **structural**: balanced HTML template, no nested modal, no identifier read
  by the JavaScript that exists nowhere, no event handler in an attribute,
  parity of the translation catalogues. They catch a whole class of defects
  that are otherwise invisible.
- **interface**: a real browser, a stubbed API. They exist because an HTML
  structure defect made a feature silently inoperative without any server test
  being able to see it.

## First start

No password is written in the source: the first launch creates the single
`admin` account, with the password supplied by the environment.

```
set PYGIA_SECRET_KEY=...                   # token signing
set PYGIA_BOOTSTRAP_ADMIN_PASSWORD=...     # password of the initial account
python run_api.py
```

Without the second variable, in development, a random password is drawn and
**logged once** at startup. It is never shown again: the line scrolls past in
the flow of messages, and once `config/users.json` exists nothing reproduces
it. If lost, delete that file and restart with the variable set — it holds
only hashes, no governance data.

In production, the absence of the variable creates no account: the
installation stays closed rather than being opened by a credential everyone
knows.

## Dependency versions

`requirements.txt` carries lower bounds and describes what the code requires.
`requirements.lock` pins the exact versions the suite has run, and it is what
a server is installed from. It is recorded, not written by hand:

```
python -m tools.verrou_dependances            # reports the gap, changes nothing
python -m tools.verrou_dependances --ecrire   # updates the file
```

Without `--ecrire` the command returns 1 when the lock differs from the
installed environment, which makes it usable as is in a CI pipeline. Regenerate
the lock only after the whole suite has passed: pinning a version nothing has
run is exactly what the file exists to prevent.

## Adding an endpoint

1. Write the route in a router under `src/api/routers/`.
2. **Declare it in `security_policy.py`** with the required permission.
   Without that it answers 403.
3. If it changes governance state, add `journal: Journal =
   Depends(get_journal)` and record the action with an `Action` code.
4. Return translation codes, never sentences.
5. Add the matching keys to all three catalogues.

## Adding a language

Copy `config/locales/fr.json`, translate the values, keep every key. The tests
check key parity and substitution consistency: a missing key or a forgotten
`{parameter}` fails the suite.

The embedded manuals live in `docs/manuel/<language>/`. A section missing in a
language is served in the reference language, and the interface says so rather
than showing an empty page.

## Audit trail

`PisteAudit` writes JSON lines appended one at a time, each carrying the
fingerprint of the previous one. The module exposes no deletion, and the API
no write route — two tests check this.

To record from a route, do not handle the trail directly: declare the
`Journal` dependency. It resolves the actor from the token and the active
workspace, which prevents a caller from attributing a decision to someone else
by slipping a name into the request body.

## Frontend

No external dependency: the libraries are embedded in `frontend/vendor/`. The
product must work on a server with no outbound access.

**Two numbers, two roles.** `serve_frontend.py` rewrites the template on the
fly: it aligns the version shown at the bottom of the sidebar on
`VERSION_PRODUIT`, and the cache key of the stylesheets and scripts on a
**fingerprint of the served content**. The latter changes exactly when a file
under `frontend/` changes, and never otherwise — so there is nothing to
remember when shipping. The number written in `index.html` only makes the file
openable as-is; it never reaches the browser.

`VERSION_PRODUIT` is deduced from nothing: it is a number that speaks to
people. Raise it when a release deserves a name, not on every change.

Forbidden, and checked by the tests:

- `onclick="..."` in the template — use event delegation;
- `<a href="#">` to trigger an action — the hash router reads it as a return
  to the dashboard;
- an identifier read by `getElementById` that exists neither in the template
  nor in generated HTML;
- displayed text written into the code.

Resources carry a version number in their URL. Increment it at every frontend
delivery, otherwise browsers serve the old version.
