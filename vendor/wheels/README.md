# vendor/wheels — the repo's own copy of its Python dependencies

**This directory is why `pdfplumber` is always available.** The `.whl` files here are
committed to git, so every clone of this repo — including a fresh ephemeral cloud
container with no network access to pypi — already has the bytes it needs.

There is no download at runtime. Installing is a local file copy.

## Why vendored and not installed from pypi each session

`pypi.org` is not on this environment's network egress allowlist (verified
2026-09-12: `x-deny-reason: host_not_allowed`). Even if it were, installing at
runtime makes every price-list run depend on pypi being reachable, on the resolver
picking the same versions, and on the package not having been yanked. Vendoring
removes all three. Git is also the integrity check — the bytes that were reviewed
are the bytes that get installed.

## The one-time fetch (a maintenance step, not a runtime step)

Needs `pypi.org` and `files.pythonhosted.org` temporarily on the environment's
network egress allowlist. Run it once; commit the result; close the allowlist again.

```bash
cd <repo root>

# 1. Fetch pdfplumber and its ENTIRE transitive tree as wheels, binary only.
#    --only-binary=:all: guarantees nothing ever needs a compiler, here or later.
#    Platform pinned to this container's real target: py3.11 / linux x86_64 / glibc 2.39.
pip download pdfplumber \
    --dest vendor/wheels \
    --only-binary=:all: \
    --python-version 311 --platform manylinux2014_x86_64 --implementation cp \
    --no-cache-dir

# 2. Generate the lock from what pip ACTUALLY resolved — versions and hashes.
#    Do not hand-write this; the point is that reality produces it.
pip hash vendor/wheels/*.whl > /tmp/hashes.txt
python3 scripts/write_requirements_lock.py   # see that script for the format

# 3. Verify the install works with the network OFF, exactly as a session will do it.
#    --ignore-installed is MANDATORY — see "The dpkg conflict" below.
pip install --no-index --find-links vendor/wheels --only-binary=:all: \
    --require-hashes --ignore-installed -r requirements.lock.txt
python3 -c "import pdfplumber; print(pdfplumber.__version__)"
python3 -m unittest tests.test_pdf_tooling -v

# 4. Commit the wheels AND the lock together. They are one unit.
git add vendor/wheels/*.whl requirements.lock.txt
git commit -m "vendor: pin pdfplumber <version> and its wheel tree"
```

**Expect roughly 10–20 MB.** `pdfminer.six`, `Pillow`, `pypdfium2` and
`cryptography` are the large ones. The repo was 3.24 MiB packed before this, so the
wheels will dominate its size — a deliberate trade for never depending on the
network at run time.

## The dpkg conflict — why `--ignore-installed` is mandatory

Discovered in practice 2026-09-12, first time the offline install was run for real.

`cryptography` is present in the base image as a **Debian package** (41.0.7), installed
by dpkg with no pip `RECORD` file. pip cannot uninstall what dpkg owns, so a plain
install aborts partway:

```
ERROR: Cannot uninstall cryptography 41.0.7, RECORD file not found.
       Hint: The package was installed by debian.
```

Worse, it is not atomic — that run had already uninstalled `charset-normalizer`
before hitting the error, leaving the environment mid-transaction.

`--ignore-installed` fixes it by never attempting an uninstall. pip writes to
`/usr/local/lib/python3.11/dist-packages`, which precedes `/usr/lib/python3/dist-packages`
on `sys.path`, so the vendored versions shadow dpkg's and the system copies are left
alone. Verified: `cryptography.__file__` resolves to the vendored 50.0.1.

**Do not "simplify" this by dropping `cryptography`/`cffi`/`pycparser` from the
vendored set** and relying on Debian's. `pdfminer.six` only asks for
`cryptography>=36.0.0`, so the system 41.0.7 would satisfy it today — but that makes
extraction depend on the base image, which is the opposite of why any of this is
vendored.

## Updating a version later

Same procedure, with the old wheels deleted first so stale versions cannot be
resolved by accident:

```bash
git rm vendor/wheels/*.whl
# then repeat the fetch above
```

Treat a version bump as a real change, not a chore: a parser version can change
extraction output, and this pipeline writes prices to a live POS. Re-run a known
price list and diff the extracted values before committing a bump.

## What must never be here

`pypdf` and `PyPDF2` — strict block, Albert 2026-09-12. Enforced by
`tests/test_pdf_tooling.py`.

`pypdfium2` **is** expected here despite the similar name; it is a PDFium binding
that pdfplumber depends on, unrelated to pypdf.
