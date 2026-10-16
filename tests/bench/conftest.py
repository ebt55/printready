"""One tiny generated split shared by the bench tests: `bench generate --limit 1` (one sample per
family) into a temporary root."""

import pytest

from printready.bench.generate import read_manifest
from printready.cli import main


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("bench")
    code = main(["bench", "generate", "--split", "dev", "--limit", "1", "--jobs", "1", "--root", str(root)])
    assert code == 0
    manifest = root / "data" / "bench" / "manifest-dev-limit1.jsonl"
    return root, manifest, read_manifest(manifest)
