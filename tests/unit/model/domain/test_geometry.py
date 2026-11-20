"""The channel rasters of a delineation, and the clipped fallback when no folder is given."""

from __future__ import annotations

from hydromodpy.model.domain.geometry import ChannelRasters


def test_channel_rasters_without_a_folder_keep_the_clipped_fallback() -> None:
    channel = ChannelRasters(
        enabled=False, link=None, pointer=None, accumulation=None, clipped=("/run/s.tif",)
    )

    assert channel.clipped == ("/run/s.tif",)
    assert ChannelRasters(enabled=False, link=None, pointer=None, accumulation=None).clipped == ()
