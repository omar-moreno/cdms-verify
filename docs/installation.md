# Installation

## From source

```bash
git clone https://github.com/your-org/cdms-verify.git
cd cdms-verify
pip install -e .
```

!!! tip "Use editable installs during development"
Installing with -e makes Python import directly from your working tree,
so source edits are picked up without reinstalling.

## With development and docs extras

```bash
pip install -e ".[dev,docs]"
```

- dev — pytest, pytest-cov
- docs — mkdocs, mkdocs-material, mkdocstrings[python]

## Requirements

- Python 3.9+
- click
- CDMSDataCatalog client


!!! note "About the CDMSDataCatalog dependency"
The CDMSDataCatalog client and its transitive dependencies (datacat,
requests) are only needed to run the CLI against a live catalog. The
pure helper modules (paths, scanning, database) can be imported and
tested without them.
