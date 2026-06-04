"""tests/test_setup_models.py — Tests for setup_models.py"""

import shutil
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import setup_models

FAKE_URL = "https://example.com/fake_model.onnx"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """
    Redirect BASE_DIR and OWW resources dir so tests never touch
    real files or the live OWW package.
    """
    monkeypatch.setattr(setup_models, "BASE_DIR", tmp_path)

    # Fake OWW resources dir inside tmp
    fake_oww_resources = tmp_path / "oww_resources" / "models"
    fake_oww_resources.mkdir(parents=True)
    monkeypatch.setattr(setup_models, "_get_oww_resources_dir",
                        lambda: fake_oww_resources)

    yield tmp_path, fake_oww_resources


def _write_valid_model(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 8192)


# ---------------------------------------------------------------------------
# get_oww_model_path
# ---------------------------------------------------------------------------

def test_get_oww_model_path_missing(isolate):
    _, oww_dir = isolate
    assert setup_models.get_oww_model_path() is None


def test_get_oww_model_path_present(isolate):
    _, oww_dir = isolate
    _write_valid_model(oww_dir / setup_models._MODEL_FNAME)
    result = setup_models.get_oww_model_path()
    assert result is not None
    assert result.exists()


# ---------------------------------------------------------------------------
# download_wake_word_model — skips if already present in OWW resources
# ---------------------------------------------------------------------------

def test_skips_if_model_in_oww_resources(isolate):
    _, oww_dir = isolate
    _write_valid_model(oww_dir / setup_models._MODEL_FNAME)

    with patch.object(urllib.request, "urlretrieve") as mock_dl:
        result = setup_models.download_wake_word_model(model_url=FAKE_URL)

    mock_dl.assert_not_called()
    assert setup_models._MODEL_FNAME in result


def test_skips_if_explicit_model_path_exists(isolate):
    tmp_path, _ = isolate
    explicit = tmp_path / "mymodel.onnx"
    _write_valid_model(explicit)

    with patch.object(urllib.request, "urlretrieve") as mock_dl:
        result = setup_models.download_wake_word_model(
            model_url=FAKE_URL, model_path=str(explicit)
        )

    mock_dl.assert_not_called()
    assert result == str(explicit)


# ---------------------------------------------------------------------------
# download_wake_word_model — OWW utility path
# ---------------------------------------------------------------------------

def test_oww_utility_called_when_model_absent(isolate):
    _, oww_dir = isolate
    calls = []

    def _fake_oww_dl(names):
        # Simulate OWW placing the file
        _write_valid_model(oww_dir / setup_models._MODEL_FNAME)
        calls.append(names)

    with patch("setup_models.download_models", _fake_oww_dl, create=True):
        # Patch the import inside the function
        import importlib
        import types
        fake_utils = types.ModuleType("openwakeword.utils")
        fake_utils.download_models = _fake_oww_dl
        with patch.dict("sys.modules", {"openwakeword.utils": fake_utils}):
            result = setup_models.download_wake_word_model(model_url=FAKE_URL)

    assert setup_models._MODEL_FNAME in result


# ---------------------------------------------------------------------------
# download_wake_word_model — direct urllib fallback
# ---------------------------------------------------------------------------

def test_direct_download_into_oww_resources(isolate):
    """When OWW utility fails, fall back to direct urllib download."""
    _, oww_dir = isolate

    def _fake_retrieve(url, dest, reporthook=None):
        Path(dest).write_bytes(b"\x00" * 8192)

    # Make OWW utility unavailable
    with patch.dict("sys.modules", {"openwakeword.utils": None}):
        with patch.object(urllib.request, "urlretrieve", side_effect=_fake_retrieve):
            result = setup_models.download_wake_word_model(model_url=FAKE_URL)

    assert Path(result).exists()
    assert Path(result).stat().st_size == 8192


def test_direct_download_creates_parent_dirs(isolate):
    tmp_path, _ = isolate
    explicit = tmp_path / "deep" / "nested" / "model.onnx"

    def _fake_retrieve(url, dest, reporthook=None):
        Path(dest).write_bytes(b"\x00" * 4096)

    with patch.object(urllib.request, "urlretrieve", side_effect=_fake_retrieve):
        setup_models.download_wake_word_model(
            model_url=FAKE_URL, model_path=str(explicit)
        )

    assert explicit.parent.exists()


def test_returns_absolute_path(isolate):
    _, oww_dir = isolate

    def _fake_retrieve(url, dest, reporthook=None):
        Path(dest).write_bytes(b"\x00" * 4096)

    with patch.dict("sys.modules", {"openwakeword.utils": None}):
        with patch.object(urllib.request, "urlretrieve", side_effect=_fake_retrieve):
            result = setup_models.download_wake_word_model(model_url=FAKE_URL)

    assert Path(result).is_absolute()


# ---------------------------------------------------------------------------
# _download_url — failure paths
# ---------------------------------------------------------------------------

def test_raises_on_network_error(isolate):
    tmp_path, _ = isolate
    dest = tmp_path / "model.onnx"
    with patch.object(urllib.request, "urlretrieve",
                      side_effect=Exception("connection refused")):
        with pytest.raises(RuntimeError, match="Failed to download"):
            setup_models._download_url(FAKE_URL, dest)


def test_cleans_up_partial_file_on_error(isolate):
    tmp_path, _ = isolate
    dest = tmp_path / "model.onnx"

    def _partial(url, path, reporthook=None):
        Path(path).write_bytes(b"\x00" * 512)
        raise Exception("timeout")

    with patch.object(urllib.request, "urlretrieve", side_effect=_partial):
        with pytest.raises(RuntimeError):
            setup_models._download_url(FAKE_URL, dest)

    assert not dest.exists()


def test_raises_if_file_too_small(isolate):
    tmp_path, _ = isolate
    dest = tmp_path / "model.onnx"

    def _tiny(url, path, reporthook=None):
        Path(path).write_bytes(b"\x00" * 512)

    with patch.object(urllib.request, "urlretrieve", side_effect=_tiny):
        with pytest.raises(RuntimeError, match="too small"):
            setup_models._download_url(FAKE_URL, dest)


def test_tiny_file_deleted_after_size_check(isolate):
    tmp_path, _ = isolate
    dest = tmp_path / "model.onnx"

    def _tiny(url, path, reporthook=None):
        Path(path).write_bytes(b"\x00" * 512)

    with patch.object(urllib.request, "urlretrieve", side_effect=_tiny):
        with pytest.raises(RuntimeError):
            setup_models._download_url(FAKE_URL, dest)

    assert not dest.exists()


# ---------------------------------------------------------------------------
# run_first_launch_setup
# ---------------------------------------------------------------------------

def test_first_launch_calls_download(monkeypatch):
    called = []
    monkeypatch.setattr(setup_models, "download_wake_word_model",
                        lambda **kw: called.append(True) or "/fake/model.onnx")
    setup_models.run_first_launch_setup()
    assert called


def test_first_launch_does_not_raise_on_failure(monkeypatch, capsys):
    def _fail(**kw):
        raise RuntimeError("no internet")
    monkeypatch.setattr(setup_models, "download_wake_word_model", _fail)
    setup_models.run_first_launch_setup()   # must not raise
    out = capsys.readouterr().out
    assert "WARNING" in out


def test_first_launch_prints_complete(monkeypatch, capsys):
    monkeypatch.setattr(setup_models, "download_wake_word_model",
                        lambda **kw: "/fake/model.onnx")
    setup_models.run_first_launch_setup()
    assert "complete" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Progress hook smoke tests
# ---------------------------------------------------------------------------

def test_progress_hook_full():
    setup_models._progress_hook(10, 1024, 10240)   # 100%


def test_progress_hook_partial():
    setup_models._progress_hook(3, 1024, 10240)    # ~30%


def test_progress_hook_unknown_total():
    setup_models._progress_hook(5, 1024, -1)       # total size unknown
