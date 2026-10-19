from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


def fetch_json(url: str) -> list[dict[str, object]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def download(url: str, target: Path, size: int, sha256: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == size:
        return
    temporary = target.with_suffix(target.suffix + ".part")
    failures = 0
    while (temporary.stat().st_size if temporary.exists() else 0) < size:
        offset = temporary.stat().st_size if temporary.exists() else 0
        try:
            end = min(offset + 16 * 1024 * 1024 - 1, size - 1)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "skytrace-model-fetch/1",
                    "Range": f"bytes={offset}-{end}",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                if offset and response.status != 206:
                    temporary.unlink(missing_ok=True)
                    offset = 0
                with temporary.open("ab" if offset else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            written = temporary.stat().st_size
            if written > size:
                raise OSError(f"expected {size} bytes, received {written}")
            print(f"{target.name}: {written}/{size} bytes", flush=True)
            failures = 0
        except Exception as exc:
            failures += 1
            if failures >= 8:
                raise
            print(f"{target.name}: resuming after {exc}", flush=True)
            time.sleep(min(failures * 2, 10))

    written = temporary.stat().st_size
    if written != size:
        raise OSError(f"expected {size} bytes, received {written}")
    if sha256:
        digest = hashlib.sha256()
        with temporary.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            temporary.unlink(missing_ok=True)
            raise OSError("SHA-256 checksum mismatch")
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--metadata-endpoint", default="https://hf-mirror.net")
    parser.add_argument(
        "--download-endpoint",
        default="https://modelscope.cn/models/pengzhendong",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repository = f"Systran/faster-whisper-{args.model}"
    quoted_repository = urllib.parse.quote(repository, safe="/")
    metadata_endpoint = args.metadata_endpoint.rstrip("/")
    files = fetch_json(
        f"{metadata_endpoint}/api/models/{quoted_repository}/tree/main?recursive=true"
    )
    output = Path(args.output)
    selected = [item for item in files if item.get("type") == "file" and item.get("path") not in {"README.md", ".gitattributes"}]
    if not selected:
        raise RuntimeError(f"No model files found for {repository}")
    for item in selected:
        path = str(item["path"])
        lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
        checksum = str(lfs.get("oid")) if lfs.get("oid") else None
        download_endpoint = args.download_endpoint.rstrip("/")
        url = (
            f"{download_endpoint}/faster-whisper-{args.model}/resolve/master/"
            f"{urllib.parse.quote(path)}"
        )
        download(url, output / path, int(item["size"]), checksum)


if __name__ == "__main__":
    main()
