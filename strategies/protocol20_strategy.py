from datetime import datetime, timedelta
from utils.tiingo_utils import get_price_at_date
import pandas as pd

def get_return_at_date(ticker, days, current_date, df_cache=None):
    if isinstance(current_date, str):
        curr_dt = pd.to_datetime(current_date)
    else:
        curr_dt = pd.to_datetime(current_date)
        
    past_dt = curr_dt - timedelta(days=days)
    
    price_now = get_price_at_date(ticker, curr_dt, df_cache)
    price_past = get_price_at_date(ticker, past_dt, df_cache)
    
    if price_now is None or price_past is None or price_past == 0:
        return None
        
    return (price_now / price_past) - 1

def calculate_13612w_score(ticker, current_date, df_cache=None):
    r1 = get_return_at_date(ticker, 30, current_date, df_cache)
    r3 = get_return_at_date(ticker, 90, current_date, df_cache)
    r6 = get_return_at_date(ticker, 180, current_date, df_cache)
    r12 = get_return_at_date(ticker, 365, current_date, df_cache)
    
    if None in [r1, r3, r6, r12]:
        return None
        
    return (12 * r1) + (4 * r3) + (2 * r6) + (1 * r12)

def get_vix_value(current_date, fred_cache=None):
    if fred_cache is None or 'VIXCLS' not in fred_cache:
        return None
        
    df = fred_cache['VIXCLS']
    target_ts = pd.to_datetime(current_date).normalize()
    
    available_dates = df.index[df.index <= target_ts]
    if len(available_dates) == 0:
        return None
        
    latest_date = available_dates[-1]
    return df.loc[latest_date]['value']

def protocol20_strategy(total_asset_value, current_date=None, df_cache=None, fred_cache=None, vix_threshold=20.0):
    """
    Protocol 20: BAA-G4 기반 + Volatility Gate + Smart Defense
    vix_threshold: 레버리지 사용을 제한하는 VIX 기준값 (기본 20.0)
    """
    if current_date is None:
        current_date = datetime.now()
        
    # 1. 유니버스 정의
    canary_assets = ['SPY', 'EFA', 'EEM', 'AGG']
    offensive_assets = ['QLD', 'SSO', 'EFA', 'EEM']
    defensive_assets = ['IEF', 'LQD', 'BIL']
    
    all_assets = list(set(canary_assets + offensive_assets + defensive_assets))
    allocation = {asset: 0.0 for asset in all_assets}
    
    # 2. 카나리아 신호 (Risk Check)
    risk_on = True
    for asset in canary_assets:
        score = calculate_13612w_score(asset, current_date, df_cache)
        if score is None or score <= 0:
            risk_on = False
            break
            
    # 3. 자산 선택
    selected_asset = None
    
    if risk_on:
        # [Volatility Gate]
        vix = get_vix_value(current_date, fred_cache)
        use_leverage = True
        
        if vix is not None and vix >= vix_threshold:
            use_leverage = False
            
        best_score = -9999
        best_asset = None
        
        for asset in offensive_assets:
            score = calculate_13612w_score(asset, current_date, df_cache)
            if score is not None and score > best_score:
                best_score = score
                best_asset = asset
        
        if best_asset == 'QLD' and not use_leverage:
            selected_asset = 'QQQM'
            allocation['QQQM'] = 0.0 
        elif best_asset == 'SSO' and not use_leverage:
            selected_asset = 'SPY'
        else:
            selected_asset = best_asset
            
    else:
        # [Smart Defense]
        best_score = -9999
        best_defensive = 'BIL'
        
        bil_score = calculate_13612w_score('BIL', current_date, df_cache)
        if bil_score is None: bil_score = 0
        
        for asset in defensive_assets:
            if asset == 'BIL': continue
            score = calculate_13612w_score(asset, current_date, df_cache)
            if score is not None and score > best_score:
                best_score = score
                best_defensive = asset
        
        if best_score < bil_score:
            selected_asset = 'BIL'
        else:
            selected_asset = best_defensive

    if selected_asset:
        allocation[selected_asset] = float(total_asset_value)
        
    return allocation
