import os, time, requests, pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
API_KEY = os.getenv("CENSUS_API_KEY")
assert API_KEY, "CENSUS_API_KEY not set"

URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CHUNK_DIR = Path("data/raw/trade/chunks")
COLUMNS = ["I_COMMODITY", "CTY_CODE", "GEN_VAL_MO", "CAL_DUT_MO", "GEN_QY1_MO"]
MIN_YEAR, WORKERS, TIMEOUT, RETRIES = 2023, 6, 100, 4
SKIP_CH = {77}  # reserved in HS, no data

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"


class TooBig(Exception):
    pass


def fetch_prefix(month, prefix):
    params = {"get": ",".join(COLUMNS), "time": month, "COMM_LVL": "HS10",
              "I_COMMODITY": f"{prefix}*", "key": API_KEY}
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(URL, params=params, timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            raise TooBig
        except requests.exceptions.RequestException:
            if attempt == RETRIES:
                raise
            time.sleep(min(5 * 2 ** (attempt - 1), 60)); continue
        if r.status_code == 204:
            return pd.DataFrame(columns=COLUMNS)
        if r.status_code == 200:
            data = r.json()
            df = pd.DataFrame(data[1:], columns=data[0])
            df = df.loc[:, ~df.columns.duplicated()]   # drop the echoed duplicate column
            return df[COLUMNS]
        if r.status_code in (502, 504, 524):
            raise TooBig                      # server timed out: split right away
        if r.status_code in (429, 500, 503):
            if attempt == RETRIES:
                raise TooBig
            time.sleep(min(5 * 2 ** (attempt - 1), 60)); continue
        if attempt == RETRIES:
            raise TooBig
        time.sleep(3)


def fetch_adaptive(month, prefix):
    try:
        return fetch_prefix(month, prefix)
    except TooBig:
        if len(prefix) >= 6:
            raise RuntimeError(f"cannot split further: {month} {prefix}")
        print(f"  split: {month} {prefix}* too big -> {prefix}0-9", flush=True)
        parts = [fetch_adaptive(month, f"{prefix}{d}") for d in range(10)]
        return pd.concat(parts, ignore_index=True)


def do_chunk(task):
    yr, mo, ch = task
    out = CHUNK_DIR / f"trade_{yr}_{mo:02d}_{ch:02d}.csv"
    tmp = out.with_name(out.name + ".tmp")
    t = time.time()
    print(f"Starting: {yr}-{mo:02d}, chapter {ch:02d}", flush=True)
    try:
        df = fetch_adaptive(f"{yr}-{mo:02d}", f"{ch:02d}")
        df.to_csv(tmp, index=False)
        os.replace(tmp, out)
        print(f"  saved {yr}-{mo:02d} ch{ch:02d}: {len(df):,} rows "
              f"({time.time()-t:.0f}s)", flush=True)
        return task, len(df), None
    except Exception as e:
        return task, 0, f"{type(e).__name__}: {e}"
    finally:
        if tmp.exists():
            tmp.unlink()


def is_valid(p):
    try:
        return p.exists() and set(COLUMNS) <= set(pd.read_csv(p, nrows=0).columns)
    except Exception:
        return False


if __name__ == "__main__":
    tasks = [
        (yr, mo, ch)
        for yr in range(MIN_YEAR, 2027)
        for mo in range(1, (3 if yr == 2026 else 12) + 1)
        for ch in range(1, 100)
        if ch not in SKIP_CH
        and not is_valid(CHUNK_DIR / f"trade_{yr}_{mo:02d}_{ch:02d}.csv")
    ]
    print(f"{len(tasks):,} chunks to fetch", flush=True)

    failed, t0 = [], time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(do_chunk, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            task, n, err = f.result()
            if err:
                failed.append(task)
                print("FAILED", task, err, flush=True)
            print(f"[{i}/{len(tasks)}] failed {len(failed)} | "
                  f"{(time.time()-t0)/60:.1f} min elapsed", flush=True)

    pd.DataFrame(failed, columns=["yr", "mo", "ch"]).to_csv("failed_rerun.csv", index=False)
    print("done; failures in failed_rerun.csv")