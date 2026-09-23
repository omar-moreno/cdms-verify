# Web Report (PHP)

A read-only web page for browsing verification results by catalog path and
status. It requires only **PHP with the `pdo_sqlite` extension** — no build
step or external dependencies — and lives in the `web/` directory of the repo.

## Features

- Filter by **catalog path** with `*` and `?` wildcards (e.g. `/CDMS/Raw/*`).
- Filter by **status** (`VERIFIED`, `UNREGISTERED`, `ERROR`, or All).
- Opens the database **read-only**, safe to run alongside the verifier.

## Requirements

- PHP 7.1+ with the `pdo_sqlite` extension.

Verify the extension:

```bash
php -m | grep pdo_sqlite
```

## Configuration

Set the database path via `web/config.php` or the `CDMS_DB_PATH` environment
variable:

```bash
export CDMS_DB_PATH=/shared/verification.db
```

## Running

```bash
# Quick local test with PHP's built-in server
CDMS_DB_PATH=/path/to/verification.db php -S localhost:8000 -t web
# open http://localhost:8000
```

For Apache/Nginx, point the document root at `web/` and ensure the PHP process
user has **read** access to the database file.

## Security

- All queries use **prepared statements** — user input is never interpolated
  into SQL.
- All output is escaped with `htmlspecialchars()`.
- The database is opened read-only (`mode=ro`).

!!! warning "PHP 7 is end-of-life"
    The page is compatible with PHP 7.1+, but PHP 7.x no longer receives
    security patches. Upgrade the server to a supported PHP version when
    feasible (the page also runs on PHP 8).
