"""Uji utilitas early-warning (tanpa jaringan)."""
import time

from src.core import database as dbm


def _fresh_db(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    # db_path adalah property yang memakai data_dir, jadi otomatis mengikuti.
    dbm.init_db()


def test_minutes_since_last_alert(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    assert dbm.minutes_since_last_alert("BBCA", "SPIKE") is None
    dbm.log_alert("BBCA", "SPIKE", 6300, "tes")
    m = dbm.minutes_since_last_alert("BBCA", "SPIKE")
    assert m is not None and m < 1  # baru saja


def test_context_notes_volume_and_news(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from src.config import settings
    from src.agents.agent5_monitor import _context_notes

    # Volume terakhir jauh di atas rata-rata -> harus terdeteksi sebagai spike volume.
    vols = [1_000_000] * settings.volume_lookback_days + [5_000_000]
    dbm.save_daily_data("ANTM", {"prev_close": 3000, "volumes": vols})
    dbm.save_sentiment({"top_mentions": {"ANTM": 3}})

    notes, day_gain = _context_notes("ANTM", 3300)
    assert "volume" in notes
    assert "ramai diberitakan" in notes
    assert round(day_gain, 1) == 10.0  # (3300-3000)/3000
