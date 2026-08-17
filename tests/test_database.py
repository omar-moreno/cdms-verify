"""Tests for cdms_verify.database."""

from cdms_verify.database import init_db, save_results_to_db, get_db


def test_save_and_query(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)

    results = [
        {"file_path": "/sdf/data/supercdms/data/CDMS/SNOLAB/R1/Raw/test1.dat", 
         "catalog_path": "/CDMS/SNOLAB/R1/Raw/test1.dat",
         "status": "VERIFIED", "checksum": "abc"},
        {"file_path": "/sdf/data/supercdms/data/CDMS/SNOLAB/R1/Raw/test2.dat", 
         "catalog_path": "/CDMS/SNOLAB/R1/Raw/test2.dat",
         "status": "UNREGISTERED", "checksum": "def"},
    ]
    stats = {"total": 2, "registered": 1, "unregistered": 1, "errors": 0}

    file_id = save_results_to_db(db, results, stats, 
                                "/sdf/data/supercdms/data/CDMS/SNOLAB/R1/Raw", 
                                "/CDMS/SNOLAB/R1/Raw", "SLAC")
    assert file_id == 1

    with get_db(db) as conn:
        rows = conn.execute(
            "SELECT status FROM verification_results WHERE run_id = ? ORDER BY id",
            (file_id,),
        ).fetchall()
    assert [r["status"] for r in rows] == ["VERIFIED", "UNREGISTERED"]
