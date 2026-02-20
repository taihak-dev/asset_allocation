import requests
import pandas as pd
import time
from requests.exceptions import HTTPError
from functools import lru_cache
from datetime import datetime, timedelta
from utils import db_utils

# 여기에 본인의 토큰을 넣으세요
TIINGO_API_TOKEN = "07d5b717fe02851e11d923573f1764ae8d9c2e60"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Token {TIINGO_API_TOKEN}"
}

def fetch_from_api(ticker, start_date, end_date):
    """
    순수하게 API 호출만 담당하는 내부 함수
    """
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    params = {"startDate": start_date, "endDate": end_date, "format": "json"}

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, params=params)
            if r.status_code == 429:
                backoff = 2 ** attempt
                print(f"[WARN] 429 Too Many Requests → {backoff}s 후 재시도")
                time.sleep(backoff)
                continue
            r.raise_for_status()
            data = r.json()
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df.set_index("date")
            
        except Exception as e:
            print(f"[ERROR] API fetch failed for {ticker}: {e}")
            if attempt == max_retries:
                return pd.DataFrame()
    return pd.DataFrame()

@lru_cache(maxsize=None)
def get_historical_prices(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = get_full_history(ticker, start_date)
    if df.empty:
        return df
        
    s_date = pd.to_datetime(start_date)
    e_date = pd.to_datetime(end_date)
    
    mask = (df.index >= s_date) & (df.index <= e_date)
    return df.loc[mask]


@lru_cache(maxsize=None)
def _fetch_yearly_hist(ticker: str) -> pd.DataFrame:
    end = datetime.today().strftime('%Y-%m-%d')
    start = (datetime.today() - timedelta(days=372)).strftime('%Y-%m-%d')
    return get_historical_prices(ticker, start, end)


@lru_cache(maxsize=None)
def get_latest_close(ticker: str) -> float:
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No data for {ticker}")
    return data[-1]["close"]


@lru_cache(maxsize=None)
def get_iex_last_price(ticker: str) -> float:
    url = f"https://api.tiingo.com/iex/{ticker}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    info = r.json()

    if isinstance(info, list):
        if not info:
            return None
        info = info[0]

    return info.get("tngoLast") or info.get("last")

# --- 스마트 데이터 수집 (DB + API) ---

@lru_cache(maxsize=None)
def get_full_history(ticker: str, start_date='2000-01-01') -> pd.DataFrame:
    """
    DB를 우선 확인하고, 부족한 부분만 API로 채운 뒤 전체 데이터를 반환합니다.
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    last_date_str = db_utils.get_last_date(ticker)
    
    need_fetch = False
    fetch_start = start_date
    
    if last_date_str is None:
        print(f"[INFO] {ticker}: No DB data. Fetching from {start_date}...")
        need_fetch = True
    else:
        # DB에 저장된 날짜 문자열을 파싱
        try:
            last_date = pd.to_datetime(last_date_str).date()
        except:
            last_date = datetime.strptime(last_date_str[:10], '%Y-%m-%d').date()
            
        today_date = datetime.now().date()
        
        if last_date < today_date - timedelta(days=1): 
            fetch_start = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
            print(f"[INFO] {ticker}: Update needed from {fetch_start}...")
            need_fetch = True

    if need_fetch:
        df_new = fetch_from_api(ticker, fetch_start, today_str)
        if not df_new.empty:
            db_utils.save_prices(ticker, df_new)
        else:
            print(f"[WARN] {ticker}: No new data fetched from API.")

    df_full = db_utils.load_prices(ticker, start_date)
    return df_full

def get_price_at_date(ticker: str, target_date, df_cache=None):
    if df_cache is not None and ticker in df_cache:
        df = df_cache[ticker]
    else:
        df = get_full_history(ticker)
    
    if df.empty:
        return None

    # target_date를 무조건 pd.Timestamp로 변환 (시간 제거)
    target_ts = pd.to_datetime(target_date).normalize()
    
    # df.index도 시간 제거 (혹시 모를 시간 정보 대비)
    # 하지만 df.index가 이미 normalize 되어 있다고 가정하고 비교
    # 안전하게 비교하기 위해 df.index <= target_ts 사용
    
    available_dates = df.index[df.index <= target_ts]
    
    if len(available_dates) == 0:
        return None 
        
    latest_date = available_dates[-1]
    
    if (target_ts - latest_date).days > 10:
        return None

    return df.loc[latest_date]['adjClose']
