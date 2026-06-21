"""GitHub (public/private) and zip-upload scan sources."""
import io
import pathlib
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.scanner import github_fetch as gh

client = TestClient(main.app)


# ---- github_fetch unit ----

def test_parse_repo_accepts_github_rejects_others():
    assert gh.parse_repo("https://github.com/dbt-labs/jaffle_shop") == ("dbt-labs", "jaffle_shop")
    assert gh.parse_repo("github.com/org/repo.git") == ("org", "repo")
    assert gh.parse_repo("org/repo") == ("org", "repo")
    with pytest.raises(gh.FetchError):
        gh.parse_repo("https://gitlab.com/x/y")


def test_extract_tarball_returns_top_dir(tmp_path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        content = b"select a from public.t1"
        info = tarfile.TarInfo("repo-main/m.sql")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    root = gh.extract_tarball(buf.getvalue(), tmp_path)
    assert (root / "m.sql").exists()


# ---- upload ----

def test_scan_upload_zip_builds_lineage():
    client.post("/api/demo/reset")
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as zf:
        zf.writestr("repo/models/rev.sql",
                    "create table mart.rev as select region, sum(amt) as total from public.sales group by region")
    res = client.post("/api/scan/upload?name=Uploaded&dialect=postgres", content=zb.getvalue())
    assert res.status_code == 200
    assert res.json()["files"] == 1
    edges = {(e["source"], e["target"]) for e in client.get("/api/lineage/data").json()}
    assert ("public.sales", "mart.rev") in edges


def test_scan_upload_rejects_non_zip():
    assert client.post("/api/scan/upload", content=b"not a zip").status_code == 400


# ---- github source (network mocked) ----

def test_github_public_source_create_and_run(monkeypatch):
    client.post("/api/demo/reset")

    def fake_fetch(repo_url, ref="", token=None):
        d = tempfile.mkdtemp()
        root = pathlib.Path(d) / "org-repo-sha"
        root.mkdir(parents=True)
        (root / "m.sql").write_text("create table a.b as select x from public.src")
        return root, d

    monkeypatch.setattr(gh, "fetch_to_tempdir", fake_fetch)
    src = client.post("/api/scan/sources", json={"name": "gh", "kind": "github_public", "repo_url": "https://github.com/org/repo"})
    assert src.status_code == 201 and src.json()["kind"] == "github_public"
    run = client.post(f"/api/scan/sources/{src.json()['id']}/run", json={})
    assert run.status_code == 200 and run.json()["files"] == 1
    edges = {(e["source"], e["target"]) for e in client.get("/api/lineage/data").json()}
    assert ("public.src", "a.b") in edges


def test_github_private_requires_token():
    src = client.post("/api/scan/sources", json={"name": "p", "kind": "github_private", "repo_url": "org/repo"})
    assert src.status_code == 201
    # running without a token is rejected
    assert client.post(f"/api/scan/sources/{src.json()['id']}/run", json={}).status_code == 400


def test_github_source_rejects_non_github_url():
    assert client.post("/api/scan/sources", json={"name": "x", "kind": "github_public", "repo_url": "https://evil.com/a/b"}).status_code == 400
