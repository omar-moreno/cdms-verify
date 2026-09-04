<?php
/**
 * Configuration for the CDMS Verification report page.
 *
 * The database path can be overridden with the CDMS_DB_PATH environment
 * variable (useful in containerized or multi-environment deployments).
 */

declare(strict_types=1);

// Absolute path to the verification SQLite database.
// Override via the CDMS_DB_PATH environment variable if set.
$dbPathFromEnv = getenv('CDMS_DB_PATH');
define('CDMS_DB_PATH', $dbPathFromEnv !== false
    ? $dbPathFromEnv
    : '/shared/verification.db');

// Maximum number of rows returned per query (guards against huge result sets).
define('CDMS_MAX_ROWS', 5000);
