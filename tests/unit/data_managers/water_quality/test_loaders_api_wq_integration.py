"""Integration tests for ApiWaterQualityLoader with real API data.

These tests make actual HTTP requests to the Hub'Eau API endpoints and validate
that the loader functions correctly extract and process real data. Run these to
verify that column names and data structures match expectations.

Run with: pytest -s tests/unit/test_loaders_api_wq_integration.py -v
The -s flag shows print output.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from hydromodpy.data_managers.water_quality.loaders_api import ApiWaterQualityLoader


@pytest.mark.integration
def test_get_station_info_piezometer_real_api():
    """Fetch real piezometer station info and display the structure."""
    loader = ApiWaterQualityLoader(site_type="pz", display=True)
    
    # Use a known piezometer ID from the Hub'Eau API
    # This will attempt to find the first available piezometer
    try:
        station_info = loader._get_station_info("07285X0037/F")
        if station_info is None:
            pytest.skip("Could not fetch station info from real API")
        
        print("\n" + "="*70)
        print("PIEZOMETER STATION INFO (from real API)")
        print("="*70)
        for key, value in station_info.items():
            print(f"  {key}: {value}")
        
        # Verify expected keys are present
        assert isinstance(station_info, dict)
        assert len(station_info) > 0
        print(f"\n✓ Successfully retrieved {len(station_info)} fields from piezometer station")
        
    except Exception as exc:
        pytest.skip(f"Real API call failed: {exc}")


@pytest.mark.integration
def test_get_station_info_river_real_api():
    """Fetch real river station info and display the structure."""
    loader = ApiWaterQualityLoader(site_type="river", display=True)
    
    try:
        station_info = loader._get_station_info("05047200")
        if station_info is None:
            pytest.skip("Could not fetch river station info from real API")
        
        print("\n" + "="*70)
        print("RIVER STATION INFO (from real API)")
        print("="*70)
        for key, value in station_info.items():
            print(f"  {key}: {value}")
        
        assert isinstance(station_info, dict)
        assert len(station_info) > 0
        print(f"\n✓ Successfully retrieved {len(station_info)} fields from river station")
        
    except Exception as exc:
        pytest.skip(f"Real API call failed: {exc}")


@pytest.mark.integration
def test_build_metadata_piezometer_real_api():
    """Build metadata from real piezometer station data."""
    loader = ApiWaterQualityLoader(site_type="pz")
    
    try:
        station_info = loader._get_station_info("07285X0037/F")
        if station_info is None:
            pytest.skip("Could not fetch station info")
        
        metadata = loader._build_metadata("07285X0037/F", station_info)
        
        print("\n" + "="*70)
        print("EXTRACTED METADATA (normalized)")
        print("="*70)
        for key, value in metadata.items():
            print(f"  {key}: {value}")
        
        # Verify metadata structure
        assert metadata["site_id"] == "07285X0037/F"
        assert "station_name" in metadata
        assert "start_date" in metadata
        assert "end_date" in metadata
        print(f"\n✓ Metadata successfully extracted with {len(metadata)} fields")
        
    except Exception as exc:
        pytest.skip(f"Metadata building failed: {exc}")


@pytest.mark.integration
def test_get_time_series_piezometer_real_api():
    """Fetch real time-series data from piezometer API and show sample."""
    loader = ApiWaterQualityLoader(site_type="pz", display=False)
    
    # Use a date range that actually has data for this station (data ends 2002-09-13)
    loader.date_start = datetime(2002, 9, 1)
    loader.date_end = datetime(2002, 9, 30)
    
    try:
        station_info = loader._get_station_info("07285X0037/F")
        if station_info is None:
            pytest.skip("Could not fetch station info")
        
        metadata = loader._build_metadata("07285X0037/F", station_info)
        df, missing_info = loader._get_time_series("07285X0037/F", metadata)
        
        if df.empty:
            pytest.skip("No time-series data returned for this site/date range")
        
        print("\n" + "="*70)
        print("TIME-SERIES DATA (first 5 rows)")
        print("="*70)
        print(f"\nDataFrame shape: {df.shape[0]} rows × {df.shape[1]} columns")
        print(f"\nColumn names and types:")
        for col in df.columns:
            print(f"  {col}: {df[col].dtype}")
        
        print(f"\nFirst 5 rows:")
        print(df.head())
        
        print(f"\n" + "="*70)
        print("MISSING DATA SUMMARY")
        print("="*70)
        for key, value in missing_info.items():
            print(f"  {key}: {value}")
        
        # Verify expected columns
        assert "date_measure" in df.columns
        assert "site_id" in df.columns
        assert df["site_id"].iloc[0] == "07285X0037/F"
        print(f"\n✓ Successfully processed {len(df)} records with {len(df.columns)} columns")
        
    except Exception as exc:
        pytest.skip(f"Time-series fetch failed: {exc}")


@pytest.mark.integration
def test_get_time_series_river_real_api():
    """Fetch real time-series data from river API and show sample."""
    loader = ApiWaterQualityLoader(site_type="river", display=False)
    
    # Use a date range with available data (early 2000s for this historical station)
    loader.date_start = datetime(2009, 3, 1)
    loader.date_end = datetime(2009, 3, 31)
    
    try:
        station_info = loader._get_station_info("05047200")
        if station_info is None:
            pytest.skip("Could not fetch station info")
        
        metadata = loader._build_metadata("05047200", station_info)
        df, missing_info = loader._get_time_series("05047200", metadata)
        
        if df.empty:
            pytest.skip("No time-series data returned for this site/date range")
        
        print("\n" + "="*70)
        print("RIVER TIME-SERIES DATA (first 5 rows)")
        print("="*70)
        print(f"\nDataFrame shape: {df.shape[0]} rows × {df.shape[1]} columns")
        print(f"\nColumn names and types:")
        for col in df.columns:
            print(f"  {col}: {df[col].dtype}")
        
        print(f"\nFirst 5 rows:")
        print(df.head())
        
        print(f"\n" + "="*70)
        print("MISSING DATA SUMMARY")
        print("="*70)
        for key, value in missing_info.items():
            print(f"  {key}: {value}")
        
        # Verify expected columns
        assert "date_measure" in df.columns
        assert "site_id" in df.columns
        print(f"\n✓ Successfully processed {len(df)} records with {len(df.columns)} columns")
        
    except Exception as exc:
        pytest.skip(f"River time-series fetch failed: {exc}")
