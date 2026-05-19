# Releasing `pycomprepair`

This project uses **PyPI Trusted Publishing** (OIDC) — no API tokens, no
secrets stored in GitHub. The release flow is driven by the workflow at
[`.github/workflows/release.yml`](.github/workflows/release.yml).

## One-time setup (per index)

Do this once on **TestPyPI** and once on **PyPI**. You need an account on
each index (https://test.pypi.org/account/register/ and
https://pypi.org/account/register/).

### TestPyPI

1. Go to https://test.pypi.org/manage/account/publishing/ and click
   **Add a new pending publisher**.
2. Fill in:
   - **PyPI project name**: `pycomprepair`
   - **Owner**: `alvaroo-fdez`
   - **Repository name**: `pycomprepair`
   - **Workflow filename**: `release.yml`
   - **Environment name**: `testpypi`
3. Save.

### PyPI

Identical to TestPyPI but on https://pypi.org/manage/account/publishing/ and
with **Environment name**: `pypi`.

### GitHub environments

On https://github.com/alvaroo-fdez/pycomprepair/settings/environments create
two environments (no secrets needed, just the names):

- `testpypi`
- `pypi` — add a **Required reviewers** rule so PyPI publishes always need
  manual approval. Optional but strongly recommended.

## Release a new version

### 1. Bump the version

Edit the version in two places (must stay in sync):

- [`pyproject.toml`](pyproject.toml): `version = "X.Y.Z"`
- [`src/pycomprepair/__init__.py`](src/pycomprepair/__init__.py): `__version__ = "X.Y.Z"`

Update [`CHANGELOG.md`](CHANGELOG.md) moving the **Unreleased** section
under a new `## [X.Y.Z] — YYYY-MM-DD` heading.

Commit:

```bash
git commit -am "chore(release): X.Y.Z"
```

### 2. (Optional) Smoke-test on TestPyPI

Trigger the workflow manually:

1. Open https://github.com/alvaroo-fdez/pycomprepair/actions/workflows/release.yml
2. Click **Run workflow** → target = `testpypi` → **Run**.
3. Once it succeeds, install in a fresh venv to validate:

   ```bash
   python -m venv /tmp/check && source /tmp/check/bin/activate
   pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ \
               pycomprepair==X.Y.Z
   pycomprepair version
   ```

### 3. Publish to real PyPI

Tag the release commit and push the tag:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

The workflow will build, attach the artifacts and (after the required
review on the `pypi` environment) publish to PyPI.

### 4. Create the GitHub Release

Once the workflow finishes, open
https://github.com/alvaroo-fdez/pycomprepair/releases/new , select the
`vX.Y.Z` tag, paste the relevant `CHANGELOG.md` section and publish.

## Rollback

Trusted Publishing does not support deleting releases. If you publish a
broken version:

1. Yank it from PyPI (`pip` will refuse to install yanked versions by
   default).
2. Publish `X.Y.(Z+1)` with the fix.
