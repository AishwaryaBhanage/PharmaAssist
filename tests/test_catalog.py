from pharmassist.catalog import docs_dir, load_catalog


def test_every_catalog_entry_points_to_an_existing_file():
    entries = load_catalog()
    missing = [e["file"] for e in entries if not (docs_dir() / e["file"]).is_file()]
    assert not missing, f"catalog entries with no file in docs/: {missing}"


def test_catalog_ids_unique_and_download_mode_valid():
    entries = load_catalog()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    assert {e["download"] for e in entries} <= {"auto", "manual"}
