import pandas_datareader as pdr
from datetime import datetime, timedelta
from utils.tiingo_utils import get_price_at_date
import pandas as pd

def get_sp500_signal_at_date(current_date, df_cache=None):
    ticker = 'SPY'
    if df_cache is not None and ticker in df_cache:
        df = df_cache[ticker]
    else:
        return None
        
    if isinstance(current_date, str):
        target_ts = pd.to_datetime(current_date)
    else:
        target_ts = pd.to_datetime(current_date)
        
    df_past = df[df.index <= target_ts]
    if len(df_past) < 200:
        return None
        
    subset = df_past.iloc[-300:].copy()
    subset['200MA'] = subset['adjClose'].rolling(window=200).mean()
    
    if pd.isna(subset['200MA'].iloc[-1]):
        return None
        
    current_price = subset['adjClose'].iloc[-1]
    current_200ma = subset['200MA'].iloc[-1]
    
    return current_price > current_200ma

def get_unemployment_signal_at_date(current_date, unemployment_df=None):
    if unemployment_df is None:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1000)
        try:
            unemployment_df = pdr.get_data_fred('UNRATE', start=start_date, end=end_date)
        except:
            return None

    if isinstance(current_date, str):
        target_ts = pd.to_datetime(current_date)
    else:
        target_ts = pd.to_datetime(current_date)
    
    df_past = unemployment_df[unemployment_df.index <= target_ts]
    
    if len(df_past) < 12:
        return None
        
    subset = df_past.iloc[-24:].copy() 
    subset['12MA'] = subset['UNRATE'].rolling(window=12).mean()
    
    if pd.isna(subset['12MA'].iloc[-1]):
        return None
        
    current_rate = subset['UNRATE'].iloc[-1]
    current_12ma = subset['12MA'].iloc[-1]
    
    return current_rate > current_12ma

def is_rate_rising(current_date, dgs10_df):
    if dgs10_df is None or dgs10_df.empty:
        return False
        
    if isinstance(current_date, str):
        target_ts = pd.to_datetime(current_date)
    else:
        target_ts = pd.to_datetime(current_date)
        
    if not isinstance(dgs10_df.index, pd.DatetimeIndex):
        dgs10_df.index = pd.to_datetime(dgs10_df.index)
        
    # [수정] 결측치 채우기 (ffill)
    # 원본 df를 건드리지 않기 위해 copy 후 처리
    # 전체 데이터를 ffill하면 느릴 수 있으므로, 필요한 부분만 잘라서 처리하거나
    # 여기서는 간단히 전체 ffill (데이터 크기가 크지 않음)
    dgs10_filled = dgs10_df.ffill()
        
    df_past = dgs10_filled[dgs10_filled.index <= target_ts]
    
    if len(df_past) < 220:
        return False
        
    subset = df_past.iloc[-300:].copy()
    col_name = subset.columns[0] 
    
    subset[col_name] = pd.to_numeric(subset[col_name], errors='coerce')
    subset['MA'] = subset[col_name].rolling(window=200).mean()
    
    if pd.isna(subset['MA'].iloc[-1]) or pd.isna(subset[col_name].iloc[-1]):
        # print(f"[DEBUG] NaN value at {target_ts.date()}")
        return False
        
    current_rate = subset[col_name].iloc[-1]
    current_ma = subset['MA'].iloc[-1]
    
    is_rising = current_rate > current_ma
    
    # 디버깅: 2022년 6월 데이터 확인
    # if target_ts.year == 2022 and target_ts.month == 6 and target_ts.day < 5:
    #     print(f"[DEBUG] {target_ts.date()} Rate: {current_rate:.2f}, MA: {current_ma:.2f}, Rising: {is_rising}")
        
    return is_rising

def laa_strategy(total_asset_value, current_date=None, df_cache=None, unemployment_df=None, dgs10_df=None, use_smart_bond=False):
    if current_date is None:
        current_date = datetime.now()
        
    fixed_assets = ['IWD', 'GLD', 'IEF']
    
    if use_smart_bond:
        if is_rate_rising(current_date, dgs10_df):
            # print(f"[SMART BOND] {current_date.date()} Rate Rising -> Switch IEF to BIL")
            fixed_assets = ['IWD', 'GLD', 'BIL']
    
    allocation = {asset: float(total_asset_value * 0.25) for asset in fixed_assets}
    
    sp500_signal = get_sp500_signal_at_date(current_date, df_cache)
    unemployment_signal = get_unemployment_signal_at_date(current_date, unemployment_df)
    
    if sp500_signal is None or unemployment_signal is None:
        allocation['QQQM'] = 0.0
        allocation['SHY'] = float(total_asset_value * 0.25)
        return allocation

    if sp500_signal and not unemployment_signal:
        allocation['QQQM'] = float(total_asset_value * 0.25)
        allocation['SHY'] = 0.0
    else:
        allocation['QQQM'] = 0.0
        allocation['SHY'] = float(total_asset_value * 0.25)

    return allocation
