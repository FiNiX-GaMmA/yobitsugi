# Fix prompt addenda

`generate_fix.py` looks up the section that matches a finding's `type` and appends it
to the prompt. The format must stay: each section is `## <TYPE>` followed by prose.

## SQL_INJECTION

Replace string interpolation with parameterised queries using the library's binding
syntax. Examples:
- Python `sqlite3` / `psycopg2`: `cur.execute("SELECT ... WHERE id = ?", (uid,))` or
  `%s` placeholders for psycopg2.
- Python `SQLAlchemy`: use `text()` with `:name` binds, or use the ORM.
- Node `pg`: `client.query('SELECT ... WHERE id = $1', [uid])`.
- Node `mysql2`: `?` placeholders with an array of values.
- Go `database/sql`: `db.Query("... WHERE id = ?", uid)` or `$1` for pgx.
- Ruby ActiveRecord: `User.where("id = ?", id)`.
- PHP PDO: `prepare()` + `execute([...])` with named or positional binds.

Never concatenate or interpolate user input into the query body, even with escaping.

## XSS

Use the framework's safe-by-default rendering. Don't introduce raw/innerHTML/dangerouslySetInnerHTML
unless absolutely necessary, and then sanitize first with a vetted library
(DOMPurify, bleach, sanitize-html). For server-rendered templates, ensure auto-escaping
is on (Jinja2 default, Django default, ERB `<%= %>` for Rails).

If the finding is in attribute context (e.g. `href="..."`), URL-encode the value too,
and reject `javascript:` schemes.

## HARDCODED_SECRET

Replace the literal with a lookup. Order of preference:
1. Environment variable: `os.environ["FOO"]` / `process.env.FOO` etc.
2. A secrets manager client (AWS Secrets Manager, GCP Secret Manager, Vault).
3. A config file outside the repo, referenced by path in an env var.

Also: the secret IS NOW LEAKED. The diff should be accompanied by a note (in a comment
or commit message section) reminding the user to rotate the credential. If you can,
add a comment in the source like `# Rotate: <key-name> was committed; rotate ASAP.`

If the finding is in a test fixture, ensure the replacement still works for tests —
typically by reading from an env var with a safe default like `"test-secret"`.

## COMMAND_INJECTION

Avoid `shell=True` (Python), `exec` with concatenation (JS), backticks/`system()` with
user input. Use the language's array-form spawn:
- Python: `subprocess.run([...], shell=False, check=True)`.
- Node: `child_process.execFile(file, [args], cb)` — never `exec()` with a built string.
- Go: `exec.Command(name, args...)`.
- Ruby: `system(prog, *args)` array form.
If a shell is unavoidable, validate input against a strict allow-list, and quote with
`shlex.quote` / `shellescape`.

## PATH_TRAVERSAL

After resolving the user-supplied path, check it's inside the intended base directory:
- Python: `base = pathlib.Path(base).resolve(); target = (base / user).resolve();
  if base not in target.parents: raise ValueError(...)`.
- Node: `path.resolve(base, user).startsWith(path.resolve(base) + path.sep)`.
- Go: `filepath.Rel(base, target)` and check the result doesn't start with `..`.

Reject input containing null bytes outright.

## INSECURE_DESERIALIZATION

Don't deserialize untrusted input with formats that can construct arbitrary objects:
no Python `pickle`, no PHP `unserialize`, no Ruby `Marshal.load`, no Java `ObjectInputStream`
on untrusted bytes. Replace with JSON (or another data-only format like CBOR / msgpack).
If the project genuinely needs object graphs, use a safe-list / whitelist approach
(e.g. `pickle.Unpickler` subclass with a strict `find_class`).

## WEAK_CRYPTO

Replace:
- MD5 / SHA-1 used for integrity or signing → SHA-256 (or SHA-3, BLAKE2).
- Password hashing with raw SHA-* → `bcrypt`, `argon2`, `scrypt`, or `pbkdf2_hmac`.
- ECB mode → GCM (or at minimum CBC with a unique IV + HMAC).
- Hardcoded IV / nonce → cryptographically random per encryption.
- `DES`, `3DES`, `RC4` → AES-256-GCM (or ChaCha20-Poly1305).
- Custom KDFs → standard ones (HKDF, PBKDF2, Argon2).

## SSRF

Validate the destination of any outbound HTTP request initiated from user input:
- Resolve the hostname first; reject if it's in private/loopback/link-local ranges
  (RFC1918, 127.0.0.0/8, 169.254.0.0/16, ::1, fc00::/7, etc.).
- Block redirects to those ranges too (`allow_redirects=False` + manual check).
- Use an allow-list of permitted destinations if at all possible.

## OPEN_REDIRECT

After building the redirect target, ensure it's either a relative path (starts with `/`
and not `//`) or matches an allow-list of host prefixes. Reject `javascript:` and
`data:` schemes.

## VULNERABLE_DEPENDENCY

Update the manifest entry to the patched version. For each ecosystem:
- Python `requirements.txt`: `pkg==X.Y.Z` (or `>=X.Y.Z,<NEXT_MAJOR`).
- Python `pyproject.toml`: edit `[project] dependencies` / `[tool.poetry.dependencies]`.
- Node `package.json`: edit `dependencies` / `devDependencies` and remind the user
  to run `npm install` to update the lockfile.
- Go: `go.mod` `require` block; mention `go mod tidy`.
- Ruby: `Gemfile`; mention `bundle update <gem>`.
- Rust: `Cargo.toml`; mention `cargo update -p <crate>`.
If the patched version is unknown, return CANNOT_FIX rather than guessing.

## OTHER

Use your judgment. Make the smallest change that resolves the finding while
preserving behavior. If you can't tell what the right fix is from the snippet,
prefer CANNOT_FIX to a guess.
