from datetime import datetime, timedelta
from utils.tiingo_utils import get_price_at_date

def get_12_month_return_at_date(ticker, current_date, df_cache=None):
    # current_date 기준 1년 전 날짜 계산
    if isinstance(current_date, str):
        curr_dt = datetime.strptime(current_date, '%Y-%m-%d')
    else:
        curr_dt = current_date
        
    start_dt = curr_dt - timedelta(days=365)
    
    end_price = get_price_at_date(ticker, curr_dt, df_cache)
    start_price = get_price_at_date(ticker, start_dt, df_cache)
    
    if end_price is None or start_price is None or start_price == 0:
        return None
        
    return (end_price / start_price) - 1

def original_dual_momentum_strategy(total_asset_value, current_date=None, df_cache=None):
    if current_date is None:
        current_date = datetime.now()
        
    tickers = ['VOO', 'EFA', 'AGG', 'BIL']
    rets = {t: get_12_month_return_at_date(t, current_date, df_cache) for t in tickers}
    
    # 데이터 부족 시 처리
    if any(v is None for v in rets.values()):
        # print(f"[WARN] ODM: Missing data at {current_date}")
        return {t: 0.0 for t in tickers} # 안전하게 현금 보유 혹은 0 리턴

    if rets['VOO'] > rets['BIL']:
        selected = 'VOO' if rets['VOO'] > rets['EFA'] else 'EFA'
    else:
        selected = 'AGG'
        
    alloc = dict.fromkeys(tickers, 0.0)
    alloc[selected] = float(total_asset_value)
    return alloc
