import os
import sys
import tempfile
from pathlib import Path

# make the package and the test helpers importable without installing
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Point the whole suite at a throwaway data directory BEFORE anything imports
# the package. Without this the tests read and write the real one: a Studio
# would load the MIDI channel this machine happens to have learned, and a run
# on a developer's laptop would pass or fail depending on what their TR-8S had
# told it. Anything that genuinely wants the real catalogue or backups reads
# them through an explicit path and is skipped when they are absent.
_TMP = Path(tempfile.mkdtemp(prefix="tr8s-tests-"))
os.environ["TR8S_DATA"] = str(_TMP)

# A fixed 117-tone catalogue, so anything that chooses sounds by measurement
# chooses from the same set on every machine. Without it kit.auto_build either
# reads whatever this particular TR-8S has been swept into, or finds nothing.
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tones.json"
if _FIXTURE.is_file():
    import shutil
    shutil.copy(_FIXTURE, _TMP / "tones.json")


import pytest


@pytest.fixture(autouse=True)
def _clean_settings():
    """
    Start every test with no remembered settings.

    The studio persists what it learns about the machine (which MIDI channel
    carries the pattern), so without this a test that exercises the learning
    leaks its result into whatever runs next, and the suite passes or fails
    depending on the order it happens to run in.
    """
    f = _TMP / "studio.json"
    if f.exists():
        f.unlink()
    yield
    if f.exists():
        f.unlink()
