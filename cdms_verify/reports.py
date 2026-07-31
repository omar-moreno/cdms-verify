"""CSV and HTML report generation.

Renders verification results into human-readable artifacts. The CSV report is
a flat table suitable for spreadsheets and downstream tooling; the HTML report
is a self-contained dark-themed page with client-side column sorting.

Functions
---------
get_status_color
    Map a status string to a hex color for the HTML report.
generate_csv_report
    Write results to a CSV file.
generate_html_report
    Write results and summary statistics to an HTML file.

Notes
-----
Status strings are normalized to ``VERIFIED``, ``UNREGISTERED``, and
``ERROR``. The HTML color and sort-priority maps recognize all three so that
every row renders with a meaningful color.
"""

from __future__ import annotations

import csv
from datetime import datetime
from typing import Any, Dict, List

#: Sort priority used by the HTML status column (lower sorts first).
STATUS_PRIORITY: Dict[str, int] = {
    "VERIFIED": 1,
    "UNREGISTERED": 2,
    "ERROR": 3,
}

#: Report column order shared by the CSV and HTML renderers.
FIELDNAMES = ["file_path", "catalog_path", "status", "checksum"]


def get_status_color(status: str) -> str:
    """Return the hex color associated with a verification status.

    Parameters
    ----------
    status : str
        A status string such as ``VERIFIED``, ``UNREGISTERED``, or ``ERROR``.

    Returns
    -------
    str
        A hex color string (e.g. ``#00ff9d``). Unknown statuses fall back to a
        neutral gray.

    Examples
    --------
    >>> get_status_color("VERIFIED")
    '#00ff9d'
    >>> get_status_color("SOMETHING_ELSE")
    '#a0a0a0'
    """
    return {
        "VERIFIED": "#00ff9d",
        "UNREGISTERED": "#ff4d4d",
        "ERROR": "#ff6b6b",
    }.get(status, "#a0a0a0")


def generate_csv_report(results: List[Dict[str, Any]], output_path: str) -> None:
    """Write verification results to a CSV file.

    Parameters
    ----------
    results : list of dict
        Per-file result rows. Each dict must contain the keys listed in
        :data:`FIELDNAMES`.
    output_path : str
        Destination path for the CSV file. Overwritten if it exists.

    Examples
    --------
    >>> generate_csv_report(results, "report.csv")  # doctest: +SKIP
    """
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)


def generate_html_report(
    results: List[Dict[str, Any]],
    stats: Dict[str, int],
    output_path: str,
) -> None:
    """Write a dark-themed, sortable HTML report.

    Parameters
    ----------
    results : list of dict
        Per-file result rows. Each dict must contain ``file_path``,
        ``catalog_path``, ``status``, and ``checksum``.
    stats : dict of str to int
        Run-level summary with the keys ``total``, ``registered``,
        ``unregistered``, and ``errors``.
    output_path : str
        Destination path for the HTML file. Overwritten if it exists.

    Notes
    -----
    The generated page is fully self-contained (inline CSS and JavaScript) so
    it can be opened directly in a browser or served statically without any
    additional assets. Clicking a table header sorts by that column; the
    status column sorts by :data:`STATUS_PRIORITY` via a ``data-sort``
    attribute.

    Examples
    --------
    >>> generate_html_report(results, stats, "report.html")  # doctest: +SKIP
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows_html = ""
    for r in results:
        color = get_status_color(r["status"])
        priority = STATUS_PRIORITY.get(r["status"], 99)
        rows_html += f"""
        <tr>
            <td title="{r['file_path']}">{r['file_path']}</td>
            <td title="{r['catalog_path']}">{r['catalog_path']}</td>
            <td style="color: {color}; font-weight: bold; text-transform: uppercase;" data-sort="{priority}">{r['status']}</td>
            <td style="font-family: monospace; color: #d1d1d1;">{r['checksum'] or 'N/A'}</td>
        </tr>
        """

    html_content = _HTML_TEMPLATE.format(
        timestamp=timestamp,
        total=stats["total"],
        registered=stats["registered"],
        unregistered=stats["unregistered"],
        errors=stats["errors"],
        rows_html=rows_html,
    )

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html_content)


# The HTML template is kept module-level to keep generate_html_report focused
# on data assembly. Double braces escape literal braces for str.format.
_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDMS Verification Report (Dark Mode)</title>
    <style>
        :root {{
            --bg-color: #121212; --card-bg: #1e1e1e; --text-main: #e0e0e0;
            --text-muted: #a0a0a0; --border-color: #333333;
            --accent-blue: #2196f3; --neon-green: #00ff9d; --bright-red: #ff4d4d;
        }}
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0;
                padding: 20px; background-color: var(--bg-color); color: var(--text-main); }}
        h1 {{ color: var(--text-main); border-bottom: 2px solid var(--accent-blue); padding-bottom: 10px; }}
        .summary {{ background: var(--card-bg); padding: 20px; border-radius: 8px;
                    margin-bottom: 25px; display: flex; flex-wrap: wrap; gap: 20px;
                    border: 1px solid var(--border-color); }}
        .summary-item {{ display: flex; flex-direction: column; min-width: 120px; }}
        .summary-label {{ font-size: 0.85em; color: var(--text-muted);
                          text-transform: uppercase; letter-spacing: 1px; }}
        .summary-value {{ font-size: 1.4em; font-weight: bold; margin-top: 5px; }}
        .table-wrapper {{ overflow-x: auto; background: var(--card-bg);
                          border-radius: 8px; border: 1px solid var(--border-color); }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.95em; }}
        th, td {{ padding: 14px 16px; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ background-color: #2c2c2c; color: var(--accent-blue); font-weight: 600;
              text-transform: uppercase; font-size: 0.85em; position: sticky; top: 0;
              cursor: pointer; user-select: none; }}
        th:hover {{ background-color: #3a3a3a; }}
        th.sorted-asc::after {{ content: " \\25B2"; font-size: 0.8em; }}
        th.sorted-desc::after {{ content: " \\25BC"; font-size: 0.8em; }}
        tr:hover {{ background-color: #2a2a2a; }}
        .footer {{ margin-top: 30px; font-size: 0.85em; color: var(--text-muted);
                   text-align: center; border-top: 1px solid var(--border-color); padding-top: 20px; }}
    </style>
</head>
<body>
    <h1>CDMS Data Catalog Verification Report</h1>
    <div class="summary">
        <div class="summary-item"><span class="summary-label">Generated</span><span class="summary-value">{timestamp}</span></div>
        <div class="summary-item"><span class="summary-label">Total Files</span><span class="summary-value">{total}</span></div>
        <div class="summary-item"><span class="summary-label">Verified</span><span class="summary-value" style="color: var(--neon-green);">{registered}</span></div>
        <div class="summary-item"><span class="summary-label">Unregistered</span><span class="summary-value" style="color: var(--bright-red);">{unregistered}</span></div>
        <div class="summary-item"><span class="summary-label">Errors</span><span class="summary-value" style="color: var(--bright-red);">{errors}</span></div>
    </div>
    <div class="table-wrapper">
        <table id="reportTable">
            <thead>
                <tr>
                    <th onclick="sortTable(0)">Local File Path</th>
                    <th onclick="sortTable(1)">Catalog Path</th>
                    <th onclick="sortTable(2)">Status</th>
                    <th onclick="sortTable(3)">Checksum</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    <div class="footer">Generated by CDMS Verify \\2022 Click headers to sort</div>
    <script>
        function sortTable(n) {{
            var table = document.getElementById("reportTable");
            var switching = true, dir = "asc", switchcount = 0;
            var headers = table.getElementsByTagName("th");
            for (var h = 0; h < headers.length; h++) {{
                headers[h].classList.remove("sorted-asc", "sorted-desc");
            }}
            while (switching) {{
                switching = false;
                var rows = table.rows;
                for (var i = 1; i < (rows.length - 1); i++) {{
                    var shouldSwitch = false;
                    var x = rows[i].getElementsByTagName("TD")[n];
                    var y = rows[i + 1].getElementsByTagName("TD")[n];
                    if (n === 2) {{
                        var xVal = parseInt(x.getAttribute("data-sort"));
                        var yVal = parseInt(y.getAttribute("data-sort"));
                        if (dir == "asc" ? xVal > yVal : xVal < yVal) {{ shouldSwitch = true; break; }}
                    }} else {{
                        var xc = x.innerHTML.toLowerCase(), yc = y.innerHTML.toLowerCase();
                        if (dir == "asc" ? xc > yc : xc < yc) {{ shouldSwitch = true; break; }}
                    }}
                }}
                if (shouldSwitch) {{
                    rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                    switching = true; switchcount++;
                }} else if (switchcount == 0 && dir == "asc") {{
                    dir = "desc"; switching = true;
                }}
            }}
            headers[n].classList.add(dir == "asc" ? "sorted-asc" : "sorted-desc");
        }}
    </script>
</body>
</html>
"""
