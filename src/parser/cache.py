"""Hash-verified, atomic, replayable source acquisition."""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen, url2pathname


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Cache:
    def __init__(self, root, offline=False, refresh=False, timeout=60, retries=3):
        if offline and refresh:
            raise ValueError("--offline and --refresh are mutually exclusive")
        self.root = Path(root)
        self.offline, self.refresh = offline, refresh
        self.timeout, self.retries = timeout, retries
        self.sources = {}

    def get(self, url, expected_sha256=None):
        key = digest(url.encode())
        metadata = self.root / "urls" / (key + ".json")
        if metadata.exists() and not self.refresh:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            if record.get("http_status") == 404:
                raise HTTPError(url, 404, "cached confirmed absence", {}, None)
            data = (self.root / "objects" / record["sha256"]).read_bytes()
            if digest(data) != record["sha256"]:
                raise ValueError(f"cache corruption for {url}; use --refresh to reacquire")
        else:
            parsed = urlparse(url)
            if parsed.scheme == "file":
                data = Path(url2pathname(unquote(parsed.path))).read_bytes()
            elif parsed.scheme in ("https", "http"):
                if self.offline:
                    raise ValueError(f"offline cache miss: {url}")
                for attempt in range(self.retries):
                    try:
                        request = Request(url, headers={"User-Agent": "oregon-law-parser/0.1", "Accept": "application/json, text/html, application/pdf"})
                        with urlopen(request, timeout=self.timeout) as response:
                            data = response.read()
                        break
                    except (HTTPError, URLError, TimeoutError) as error:
                        if isinstance(error, HTTPError) and error.code == 404:
                            atomic_write(metadata, json.dumps({"source_url": url, "http_status": 404}).encode())
                        if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                            raise
                        if attempt + 1 == self.retries:
                            raise
                        time.sleep(min(2 ** attempt, 8))
            else:
                raise ValueError(f"unsupported source URL: {url}")
            record = {"source_url": url, "sha256": digest(data), "bytes": len(data)}
            if expected_sha256 and record["sha256"] != expected_sha256:
                raise ValueError(f"source hash mismatch: {url}")
            atomic_write(self.root / "objects" / record["sha256"], data)
            atomic_write(metadata, json.dumps(record, sort_keys=True).encode())
        if expected_sha256 and digest(data) != expected_sha256:
            raise ValueError(f"source hash mismatch: {url}")
        self.sources[url] = record
        return data
