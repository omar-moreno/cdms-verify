"""Tests for cdms_verify.paths."""

from pathlib import Path

import pytest

from cdms_verify.paths import extract_catalog_path, normalize_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", "/CDMS"),
        ("/", "/CDMS"),
        ("/CDMS/Raw/Run1/", "/CDMS/Raw/Run1"),
        ("/CUTE/Raw", "/CDMS/CUTE/Raw"),
        ("  /CDMS/Data/  ", "/CDMS/Data"),
        ("//Raw//Run1//", "/CDMS/Raw/Run1"),
    ],
)
def test_normalize_path(raw, expected):
    assert normalize_path(raw) == expected


def test_extract_catalog_path_found():
    p = Path("/home/user/CDMS/Raw/run1.dat")
    assert extract_catalog_path(p) == "/CDMS/Raw/run1.dat"


def test_extract_catalog_path_missing():
    assert extract_catalog_path(Path("/tmp/nothing/here.txt")) is None
