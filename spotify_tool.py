"""
spotify_tool.py — Control Spotify via spotipy.

Setup:
  1. Go to developer.spotify.com/dashboard → Create App
  2. Add http://localhost:8888/callback as Redirect URI
  3. Copy Client ID and Client Secret
  4. Add to config.yaml:
       spotify:
         client_id: "..."
         client_secret: "..."
         redirect_uri: "http://localhost:8888/callback"
  5. First run: browser opens for auth → token cached in data/spotify_token/

pip install spotipy
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sp():
    """Return authenticated Spotify client."""
    try:
        import spotipy  # type: ignore
        from spotipy.oauth2 import SpotifyOAuth  # type: ignore
    except ImportError:
        raise RuntimeError("spotipy not installed. Run: pip install spotipy")

    cfg = _load_cfg().get("spotify", {})
    cid = cfg.get("client_id", "").strip()
    sec = cfg.get("client_secret", "").strip()
    uri = cfg.get("redirect_uri", "http://localhost:8888/callback")

    if not cid or not sec:
        raise RuntimeError(
            "Spotify not configured. Add spotify.client_id and spotify.client_secret to config.yaml."
        )

    cache_path = str(BASE_DIR / "data" / "spotify_token")
    scope = "user-modify-playback-state user-read-playback-state user-read-currently-playing"
    auth = SpotifyOAuth(
        client_id=cid, client_secret=sec, redirect_uri=uri,
        scope=scope, cache_path=cache_path, open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def _active_device_id() -> str | None:
    """Return the ID of the active Spotify device, or None."""
    try:
        devices = _sp().devices().get("devices", [])
        active  = [d for d in devices if d.get("is_active")]
        return active[0]["id"] if active else (devices[0]["id"] if devices else None)
    except Exception:
        return None


def play_pause() -> str:
    try:
        sp    = _sp()
        state = sp.current_playback()
        if state and state.get("is_playing"):
            sp.pause_playback()
            return "Spotify paused."
        else:
            sp.start_playback()
            return "Spotify playing."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def next_track() -> str:
    try:
        _sp().next_track()
        return "Next track."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def previous_track() -> str:
    try:
        _sp().previous_track()
        return "Previous track."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def set_volume(level: int) -> str:
    """level: 0-100"""
    try:
        level = max(0, min(100, level))
        _sp().volume(level)
        return f"Spotify volume set to {level}%."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def now_playing() -> str:
    try:
        state = _sp().current_playback()
        if not state or not state.get("item"):
            return "Nothing playing on Spotify."
        item    = state["item"]
        track   = item["name"]
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        return f"Playing {track} by {artists}."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def search_and_play(query: str) -> str:
    try:
        sp      = _sp()
        results = sp.search(q=query, limit=1, type="track")
        tracks  = results.get("tracks", {}).get("items", [])
        if not tracks:
            return f"No Spotify results for '{query}'."
        track   = tracks[0]
        uri     = track["uri"]
        name    = track["name"]
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        device  = _active_device_id()
        sp.start_playback(device_id=device, uris=[uri])
        return f"Playing {name} by {artists}."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify error: {e}"


def spotify_status() -> str:
    cfg = _load_cfg().get("spotify", {})
    if not cfg.get("client_id"):
        return (
            "Spotify is not configured. Add your Spotify app credentials "
            "to config.yaml under spotify.client_id and spotify.client_secret."
        )
    try:
        _sp()
        return "Spotify is connected."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Spotify connection failed: {e}"
