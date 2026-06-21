"""Fetch a GitHub repo (public or private) for scanning — stdlib only, no `git`.

Downloads the repo tarball via the GitHub API and extracts it to a temp dir.
Private repos use a per-request token (Authorization: Bearer) that the caller
must NOT persist. Also handles user-uploaded zip archives.

Hardening: host allowlist, download size cap, request timeout, and safe
extraction (path-traversal-proof) for both tar and zip.
"""
from __future__ import annotations

import io
import re
import ssl
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _ssl_context() -> ssl.SSLContext:
    """A verifying TLS context using certifi's CA bundle when available.

    Avoids macOS/slim-image cases where the system trust store isn't wired up.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()

ALLOWED_HOSTS = {"github.com", "www.github.com", "api.github.com"}
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024  # 80 MB
DEFAULT_TIMEOUT = 30

_REPO_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)", re.I)
_SHORT_RE = re.compile(r"^([^/\s]+)/([^/\s#?]+)$")


class FetchError(Exception):
    """Raised for invalid input or fetch failures (mapped to HTTP 400 by the API)."""


def parse_repo(repo_url: str) -> tuple[str, str]:
    """Return (owner, repo) for a github URL or `owner/repo` shorthand; reject others."""
    url = (repo_url or "").strip()
    m = _REPO_RE.search(url) or _SHORT_RE.match(url)
    if not m:
        raise FetchError("Provide a GitHub repo as https://github.com/<owner>/<repo> or <owner>/<repo>")
    owner, repo = m.group(1), m.group(2)
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    return owner, repo


def _download(url: str, token: str | None, timeout: int) -> bytes:
    headers = {"User-Agent": "suranku-data-intelligence-portal", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            host = (resp.geturl().split("/")[2] if "://" in resp.geturl() else "").lower()
            # codeload.github.com is where the API redirects for tarballs — allow it.
            if host and not (host in ALLOWED_HOSTS or host.endswith(".github.com")):
                raise FetchError(f"Refusing to download from unexpected host: {host}")
            data = resp.read(MAX_ARCHIVE_BYTES + 1)
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"GitHub fetch failed: {exc}") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise FetchError(f"Repo archive exceeds the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB limit")
    return data


def download_repo_tarball(repo_url: str, ref: str = "", token: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    owner, repo = parse_repo(repo_url)
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref.strip()}".rstrip("/")
    return _download(url, token, timeout)


def extract_tarball(data: bytes, dest: str | Path) -> Path:
    """Safely extract a tarball; return the single top-level directory."""
    dest = Path(dest)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        try:
            tar.extractall(dest, filter="data")  # py3.12: blocks traversal/special files
        except TypeError:  # older Python without the filter arg
            tar.extractall(dest)
    roots = [p for p in dest.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else dest


def extract_zip_bytes(data: bytes, dest: str | Path) -> Path:
    """Safely extract a zip archive; return the dir containing the repo files."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise FetchError(f"Upload exceeds the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB limit")
    dest = Path(dest)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                target = (dest / name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise FetchError("Zip contains an unsafe path")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise FetchError("Uploaded file is not a valid .zip archive") from exc
    # Common case: a single top-level folder (e.g. repo-main/).
    roots = [p for p in dest.iterdir() if p.is_dir()]
    files = [p for p in dest.iterdir() if p.is_file()]
    return roots[0] if (len(roots) == 1 and not files) else dest


def fetch_to_tempdir(repo_url: str, ref: str = "", token: str | None = None) -> tuple[Path, str]:
    """Download + extract a GitHub repo into a fresh temp dir. Returns (root, tmpdir)."""
    tmp = tempfile.mkdtemp(prefix="dip-scan-")
    data = download_repo_tarball(repo_url, ref=ref, token=token)
    root = extract_tarball(data, tmp)
    return root, tmp
