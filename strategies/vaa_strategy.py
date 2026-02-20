from datetime import datetime, timedelta
from utils.tiingo_utils import get_price_at_date

def get_return_at_date(ticker, days, current_date, df_cache=None):
    if isinstance(current_date, str):
        curr_dt = datetime.strptime(current_date, '%Y-%m-%d')
    else:
        curr_dt = current_date
        
    past_dt = curr_dt - timedelta(days=days)
    
    price_now = get_price_at_date(ticker, curr_dt, df_cache)
    price_past = get_price_at_date(ticker, past_dt, df_cache)
    
    if price_now is None or price_past is None or price_past == 0:
        return None
        
    return (price_now / price_past) - 1

def calculate_momentum_score_at_date(ticker, current_date, df_cache=None):
    returns = {
        30: get_return_at_date(ticker, 30, current_date, df_cache),
        90: get_return_at_date(ticker, 90, current_date, df_cache),
        180: get_return_at_date(ticker, 180, current_date, df_cache),
        365: get_return_at_date(ticker, 365, current_date, df_cache)
    }

    if None in returns.values():
        return None

    return (12 * returns[30]) + (4 * returns[90]) + (2 * returns[180]) + returns[365]

def vaa_aggressive_strategy(total_asset_value, current_date=None, df_cache=None):
    if current_date is None:
        current_date = datetime.now()

    aggressive_assets = ['VOO', 'EFA', 'VWO', 'AGG']
    defensive_assets = ['LQD', 'IEF', 'SHY']
    
    all_assets = aggressive_assets + defensive_assets
    
    aggressive_scores = {asset: calculate_momentum_score_at_date(asset, current_date, df_cache) for asset in aggressive_assets}
    defensive_scores = {asset: calculate_momentum_score_at_date(asset, current_date, df_cache) for asset in defensive_assets}

    if None in aggressive_scores.values() or None in defensive_scores.values():
        return {asset: 0.0 for asset in all_assets}

    if all(score >= 0 for score in aggressive_scores.values()):
        selected_asset = max(aggressive_scores, key=aggressive_scores.get)
    else:
        selected_asset = max(defensive_scores, key=defensive_scores.get)

    allocation = {asset: 0.0 for asset in all_assets}
    allocation[selected_asset] = float(total_asset_value)

    return allocation

# --- 하위 호환성 (Legacy Support) ---
# 옛날 코드(main.py 등)에서 get_return, calculate_momentum_score를 호출할 때를 대비

def get_return(ticker, days):
    """
    오늘 날짜 기준으로 수익률 계산 (Legacy)
    """
    return get_return_at_date(ticker, days, datetime.now())

def calculate_momentum_score(ticker):
    """
    오늘 날짜 기준으로 모멘텀 스코어 계산 (Legacy)
    """
    return calculate_momentum_score_at_date(ticker, datetime.now())
