from pathlib import Path

from src.infrastructure.data.historical_volume_service import HistoricalVolumeService


def test_volume_ranking_cache_is_backend_anchored():
    backend_dir = Path(__file__).resolve().parents[1]

    assert HistoricalVolumeService.CACHE_DIR == backend_dir / "data" / "cache" / "volume_rankings"
