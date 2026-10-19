from __future__ import annotations

import hashlib
import os
import time
import urllib.request
from pathlib import Path


CHUNK_SIZE = 16 * 1024 * 1024


def download(url: str, target: Path, expected_size: int, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == expected_size:
        candidate = target
    else:
        candidate = target.with_suffix(target.suffix + ".part")
        failures = 0
        while (candidate.stat().st_size if candidate.exists() else 0) < expected_size:
            offset = candidate.stat().st_size if candidate.exists() else 0
            end = min(offset + CHUNK_SIZE - 1, expected_size - 1)
            request = urllib.request.Request(
                url,
                headers={
                    "Range": f"bytes={offset}-{end}",
                    "User-Agent": "skytrace-model-fetch/1",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    if offset and response.status != 206:
                        candidate.unlink(missing_ok=True)
                        continue
                    with candidate.open("ab" if offset else "wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                written = candidate.stat().st_size
                if written > expected_size:
                    raise OSError(f"expected {expected_size} bytes, received {written}")
                print(f"{target.name}: {written}/{expected_size} bytes", flush=True)
                failures = 0
            except Exception as exc:
                failures += 1
                if failures >= 8:
                    raise
                print(f"resuming after {exc}", flush=True)
                time.sleep(min(failures * 2, 10))

    if candidate.stat().st_size != expected_size:
        raise OSError(
            f"expected {expected_size} bytes, received {candidate.stat().st_size}"
        )
    digest = hashlib.sha256()
    with candidate.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        candidate.unlink(missing_ok=True)
        raise OSError("SHA-256 checksum mismatch")
    if candidate != target:
        candidate.replace(target)
    print(f"verified {target.name}", flush=True)


if __name__ == "__main__":
    filename = os.environ.get("MODEL_FILE", "gemma-4-E2B-it-Q4_K_M.gguf")
    download(
        os.environ["MODEL_URL"],
        Path("/models") / filename,
        int(os.environ["MODEL_SIZE"]),
        os.environ["MODEL_SHA256"],
    )
