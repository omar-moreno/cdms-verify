<?php
/**
 * CDMS Verification Report (PHP 7 compatible)
 *
 * A read-only, dependency-free (PHP + PDO SQLite) page that lets a user browse
 * verification results by catalog path (with * and ? wildcards) and filter by
 * status. Runs on any server with PHP's pdo_sqlite extension enabled.
 */

declare(strict_types=1);

require __DIR__ . '/config.php';

// Valid status values a user may filter by. (const arrays are fine in PHP 7,
// but a plain define keeps it simple and avoids class-const scoping.)
define('VALID_STATUSES', ['VERIFIED', 'UNREGISTERED', 'ERROR']);

/**
 * Open the verification database read-only.
 *
 * @return PDO A read-only PDO connection.
 * @throws RuntimeException If the database cannot be opened.
 */
function openDb(): PDO
{
    if (!file_exists(CDMS_DB_PATH)) {
        throw new RuntimeException('Database not found: ' . CDMS_DB_PATH);
    }
    // The "?mode=ro" URI opens SQLite read-only so this page can never write.
    $dsn = 'sqlite:file:' . CDMS_DB_PATH . '?mode=ro';
    $pdo = new PDO($dsn, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    return $pdo;
}

/**
 * Translate a user-supplied glob (using * and ?) into a SQL LIKE pattern.
 *
 * Literal % and _ characters in the input are escaped so they are matched
 * literally rather than acting as SQL wildcards. The returned pattern is used
 * with "LIKE ? ESCAPE '\\'".
 *
 * @param string $glob The user input, e.g. "/CDMS/Raw/*".
 * @return string A SQL LIKE pattern, e.g. "/CDMS/Raw/%".
 */
function globToLike(string $glob): string
{
    // Escape SQL LIKE special characters first so they are treated literally.
    $escaped = str_replace(['\\', '%', '_'], ['\\\\', '\\%', '\\_'], $glob);
    // Then translate glob wildcards into LIKE wildcards.
    $escaped = str_replace(['*', '?'], ['%', '_'], $escaped);
    return $escaped;
}

/**
 * Escape a value for safe HTML output.
 *
 * @param mixed $value The value to escape.
 * @return string The escaped string.
 */
function h($value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/**
 * Return a CSS color for a status value.
 *
 * @param string $status The status value.
 * @return string A hex color string.
 */
function statusColor(string $status): string
{
    switch ($status) {
        case 'VERIFIED':
            return '#00ff9d';
        case 'UNREGISTERED':
            return '#ff4d4d';
        case 'ERROR':
            return '#ff6b6b';
        default:
            return '#a0a0a0';
    }
}

/**
 * Format a POSIX mtime (float seconds) as a readable date, or '' if null.
 *
 * @param mixed $mtime The modification time.
 * @return string A formatted date, or an empty string.
 */
function formatMtime($mtime): string
{
    if ($mtime === null || $mtime === '') {
        return '';
    }
    return date('Y-m-d H:i:s', (int) $mtime);
}

/**
 * Format a byte size, or '' if null.
 *
 * @param mixed $size The size in bytes.
 * @return string A formatted size, or an empty string.
 */
function formatSize($size): string
{
    return $size === null ? '' : number_format((int) $size);
}

// --- Read and sanitize input ------------------------------------------------

$catalogPath = isset($_GET['catalog_path'])
    ? trim((string) $_GET['catalog_path'])
    : '/CDMS/*';

$status = isset($_GET['status']) ? (string) $_GET['status'] : '';
// Only accept a whitelisted status; anything else means "all".
if (!in_array($status, VALID_STATUSES, true)) {
    $status = '';
}

// --- Run the query ----------------------------------------------------------

$rows = [];
$error = null;
$truncated = false;

if ($catalogPath !== '') {
    try {
        $pdo = openDb();

        $sql = 'SELECT file_path, catalog_path, status, checksum, size, '
             . 'mtime, site, scan_timestamp '
             . 'FROM verification_results '
             . 'WHERE catalog_path LIKE ? ESCAPE ?';
        $params = [globToLike($catalogPath), '\\'];

        if ($status !== '') {
            $sql .= ' AND status = ?';
            $params[] = $status;
        }

        $sql .= ' ORDER BY catalog_path LIMIT ?';
        $params[] = CDMS_MAX_ROWS + 1; // fetch one extra to detect truncation

        $stmt = $pdo->prepare($sql);
        // Bind each parameter, using an integer type for the LIMIT value.
        foreach ($params as $i => $val) {
            $type = is_int($val) ? PDO::PARAM_INT : PDO::PARAM_STR;
            $stmt->bindValue($i + 1, $val, $type);
        }
        $stmt->execute();
        $rows = $stmt->fetchAll();

        if (count($rows) > CDMS_MAX_ROWS) {
            $truncated = true;
            $rows = array_slice($rows, 0, CDMS_MAX_ROWS);
        }
    } catch (Throwable $e) {
        $error = $e->getMessage();
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDMS Verification Report</title>
    <style>
        :root {
            --bg: #121212; --card: #1e1e1e; --text: #e0e0e0;
            --muted: #a0a0a0; --border: #333; --accent: #2196f3;
        }
        * { box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            margin: 0; padding: 20px; background: var(--bg); color: var(--text);
        }
        h1 { border-bottom: 2px solid var(--accent); padding-bottom: 10px; }
        form {
            background: var(--card); padding: 20px; border-radius: 8px;
            border: 1px solid var(--border); margin-bottom: 20px;
            display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
        }
        .field { display: flex; flex-direction: column; }
        .field label {
            font-size: .8em; color: var(--muted); text-transform: uppercase;
            letter-spacing: 1px; margin-bottom: 6px;
        }
        input[type=text], select {
            padding: 10px; font-size: 1em; background: #2a2a2a;
            color: var(--text); border: 1px solid var(--border); border-radius: 4px;
        }
        input[type=text] { min-width: 340px; }
        button {
            padding: 10px 24px; font-size: 1em; cursor: pointer;
            background: var(--accent); color: #fff; border: none; border-radius: 4px;
        }
        button:hover { background: #1976d2; }
        .hint { font-size: .8em; color: var(--muted); margin-top: 6px; }
        .meta { color: var(--muted); margin-bottom: 12px; }
        .error {
            background: #3a0d0d; border: 1px solid #ff6b6b; color: #ff9d9d;
            padding: 14px; border-radius: 6px; margin-bottom: 20px;
        }
        .warn {
            background: #3a2e00; border: 1px solid #ffcc00; color: #ffe083;
            padding: 14px; border-radius: 6px; margin-bottom: 20px;
        }
        .table-wrap {
            overflow-x: auto; background: var(--card);
            border: 1px solid var(--border); border-radius: 8px;
        }
        table { width: 100%; border-collapse: collapse; font-size: .9em; }
        th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); }
        th { background: #2c2c2c; color: var(--accent); text-transform: uppercase;
             font-size: .8em; letter-spacing: .5px; position: sticky; top: 0; }
        tr:hover { background: #2a2a2a; }
        .mono { font-family: monospace; color: #d1d1d1; }
        .empty { padding: 30px; text-align: center; color: var(--muted); }
    </style>
</head>
<body>
    <h1>CDMS Verification Report</h1>

    <form method="get" action="">
        <div class="field">
            <label for="catalog_path">Catalog Path (supports * and ?)</label>
            <input type="text" id="catalog_path" name="catalog_path"
                   value="<?php echo h($catalogPath); ?>" placeholder="/CDMS/Raw/*">
            <span class="hint">e.g. <code>/CDMS/Raw/*</code> or <code>/CDMS/*/Run?</code></span>
        </div>
        <div class="field">
            <label for="status">Status</label>
            <select id="status" name="status">
                <option value="">All</option>
                <?php foreach (VALID_STATUSES as $s): ?>
                    <option value="<?php echo h($s); ?>" <?php echo $status === $s ? 'selected' : ''; ?>>
                        <?php echo h($s); ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </div>
        <div class="field">
            <button type="submit">Search</button>
        </div>
    </form>

    <?php if ($error !== null): ?>
        <div class="error">Error: <?php echo h($error); ?></div>
    <?php endif; ?>

    <?php if ($truncated): ?>
        <div class="warn">
            Results truncated to <?php echo h((string) CDMS_MAX_ROWS); ?> rows.
            Refine your catalog path or status filter to narrow the results.
        </div>
    <?php endif; ?>

    <?php if ($error === null && $catalogPath !== ''): ?>
        <div class="meta">
            Showing <strong><?php echo h((string) count($rows)); ?></strong> file(s)
            matching <code><?php echo h($catalogPath); ?></code>
            <?php echo $status !== '' ? 'with status <code>' . h($status) . '</code>' : ''; ?>.
        </div>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Catalog Path</th>
                        <th>Status</th>
                        <th>Checksum</th>
                        <th>Size</th>
                        <th>Modified</th>
                        <th>Site</th>
                        <th>Scanned</th>
                    </tr>
                </thead>
                <tbody>
                    <?php if (count($rows) === 0): ?>
                        <tr><td colspan="7" class="empty">No matching files found.</td></tr>
                    <?php else: ?>
                        <?php foreach ($rows as $row): ?>
                            <?php
                                $checksum = (string) $row['checksum'];
                                $checksumShort = substr($checksum, 0, 16)
                                    . (strlen($checksum) > 16 ? '…' : '');
                            ?>
                            <tr>
                                <td title="<?php echo h($row['file_path']); ?>"><?php echo h($row['catalog_path']); ?></td>
                                <td style="color: <?php echo h(statusColor($row['status'])); ?>; font-weight: bold;">
                                    <?php echo h($row['status']); ?>
                                </td>
                                <td class="mono" title="<?php echo h($checksum); ?>">
                                    <?php echo h($checksumShort); ?>
                                </td>
                                <td><?php echo h(formatSize($row['size'])); ?></td>
                                <td><?php echo h(formatMtime($row['mtime'])); ?></td>
                                <td><?php echo h($row['site']); ?></td>
                                <td><?php echo h($row['scan_timestamp']); ?></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>
    <?php endif; ?>
</body>
</html>
