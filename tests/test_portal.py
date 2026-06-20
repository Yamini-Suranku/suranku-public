from backend.app import main


def test_health_returns_ok():
    assert main.health()["status"] == "ok"


def test_demo_reset_seeds_domains_and_contracts():
    body = main.reset_demo()
    assert body["domains"] == 1
    assert body["contracts"] == 3

    assert len(main.domains()) == 1
    assert len(main.contracts()) == 3


def test_demo_ingestion_creates_runs_catalogs_and_lineage():
    main.reset_demo()
    body = main.run_demo_ingestion()
    assert body["marker_id"] == "commerce-batch-001"
    assert len(body["runs"]) == 3
    assert any(run["records_deduped"] == 1 for run in body["runs"])

    runs = main.ingestion_runs()
    catalogs = main.catalogs()
    data_lineage = main.data_lineage()
    process_lineage = main.process_lineage()

    assert len(runs) == 3
    assert len(catalogs) == 9
    assert len(data_lineage) == 9
    assert len(process_lineage) == 9
    assert {table["layer"] for table in catalogs} == {"intraday", "endofday", "analytics"}


def test_chat_works_without_api_key():
    main.reset_demo()
    body = main.deterministic_answer("How does lineage work?")
    assert body["mode"] == "deterministic"
    assert "lineage" in body["answer"].lower()
