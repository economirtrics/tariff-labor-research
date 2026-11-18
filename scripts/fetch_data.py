# Used to collect BLS QCEW, LAUS, attempted to get BEA and USCIS Trade but failed.
import os
import requests
import zipfile
import pandas as pd
from io import BytesIO

# Ensure directory structure exists
os.makedirs("data/raw/qcew", exist_ok=True)
os.makedirs("data/raw/laus", exist_ok=True)
os.makedirs("data/raw/trade", exist_ok=True)

BLS_HEADERS = {"User-Agent": "amirazlan@example.com"}
API_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# ---------------------------------------------------------------------------
# 1. PULL BLS QCEW COUNTY-LEVEL DATA (Multi-Year Annual Quarterly Archives)
# ---------------------------------------------------------------------------
def fetch_qcew_annual_area_data(start_year=2021, end_year=2025):
    for year in range(start_year, end_year + 1):
        url = f"https://www.bls.gov/cew/data/files/{year}/csv/{year}_qtrly_by_area.zip"
        print(f"Downloading QCEW annual quarterly package for {year}...")
        
        response = requests.get(url, headers=BLS_HEADERS)
        if response.status_code == 200:
            z = zipfile.ZipFile(BytesIO(response.content))
            target_dir = f"data/raw/qcew/{year}"
            os.makedirs(target_dir, exist_ok=True)
            z.extractall(target_dir)
            print(f"Successfully extracted QCEW data for {year}.")
        else:
            print(f"Failed to download QCEW data for {year}. Status code: {response.status_code}")

# ---------------------------------------------------------------------------
# 2. PULL BLS LAUS COUNTY UNEMPLOYMENT DATA (Flat File)
# ---------------------------------------------------------------------------
def fetch_laus_county_data():
    url = "https://download.bls.gov/pub/time.series/la/la.data.64.County"
    print("Downloading LAUS county unemployment data...")
    
    response = requests.get(url, headers=BLS_HEADERS)
    if response.status_code == 200:
        file_path = "data/raw/laus/la_data_county.txt"
        with open(file_path, "wb") as f:
            f.write(response.content)
        print("Successfully saved LAUS county file.")
    else:
        print(f"Failed to download LAUS data. Status code: {response.status_code}")

# ---------------------------------------------------------------------------
# 3. PULL CENSUS INTERNATIONAL TRADE DATA (Year-by-Year Chunking)
# ---------------------------------------------------------------------------
def fetch_census_trade_data_by_year(api_key, start_year=2021, end_year=2025):
    """Pulls Census HTS-10 trade data year-by-year to prevent 524 timeouts."""
    url = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
    all_dfs = []
    
    for yr in range(start_year, end_year + 1):
        print(f"Pulling Census trade data for {yr}...")
        params = {
            "get": "I_COMMODITY,CTY_CODE,GEN_VAL_MO,CAL_DUT_MO,GEN_QY1_MO",
            "time": f"from {yr}-01 to {yr}-12",
            "COMM_LVL": "HS10",
            "key": api_key
        }
        
        response = requests.get(url, params=params, headers=API_HEADERS, timeout=120)
        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data[1:], columns=data[0])
            all_dfs.append(df)
            print(f"Successfully retrieved Census data for {yr}.")
        else:
            print(f"Census API Warning for {yr}: {response.text}")
            
    if all_dfs:
        full_df = pd.concat(all_dfs, ignore_index=True)
        for col in ["GEN_VAL_MO", "CAL_DUT_MO", "GEN_QY1_MO"]:
            if col in full_df.columns:
                full_df[col] = pd.to_numeric(full_df[col], errors="coerce")
        full_df["realized_tariff_rate"] = full_df["CAL_DUT_MO"] / full_df["GEN_VAL_MO"]
        full_df.to_csv("data/raw/trade/census_trade_raw.csv", index=False)
        print("Successfully consolidated and saved multi-year Census trade data.")


    
    # QCEW and LAUS already downloaded locally; commented out to preserve bandwidth
    # fetch_qcew_annual_area_data(start_year=2021, end_year=2025)
    # fetch_laus_county_data()
    
    # Active Census trade data pull (uncomment once Census API key is inserted)

# ---------------------------------------------------------------------------
# Execution Block (Insert your actual API keys here)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # QCEW county files and the LAUS county flat file.
    # Customs data comes from fetch_missing.py (Census trade API).
    fetch_qcew_annual_area_data(start_year=2024, end_year=2024)
    fetch_laus_county_data()

# Execute full multi-year panel data acquisition
    #fetch_qcew_annual_area_data(start_year=2021, end_year=2025)
    #fetch_laus_county_data()
    #fetch_census_trade_data(CENSUS_KEY)
    #fetch_bea_io_tables(BEA_KEY)
    fetch_census_trade_data_by_year(CENSUS_KEY, start_year=2021, end_year=2025)