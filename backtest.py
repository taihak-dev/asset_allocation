import pandas as pd
import pandas_datareader as pdr
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from utils import tiingo_utils, db_utils
from strategies.baa_strategy import baa_g4_strategy
from strategies.laa_strategy import laa_strategy
import os
import traceback

# 1. 설정
START_DATE = '2010-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')
INITIAL_CAPITAL = 10000 

# 전략 비중 설정 (BAA 비중만 조절하면 LAA는 자동 계산)
BAA_WEIGHT = 0.6  # 예: 0.4 = 40%
LAA_WEIGHT = 1.0 - BAA_WEIGHT

# 사용되는 모든 티커 (BAA + LAA)
ALL_TICKERS = list(set([
    'IWD', 'GLD', 'IEF', 'QQQM', 'SHY', 'SPY', # LAA
    'SPY', 'EFA', 'EEM', 'AGG', 'QLD', 'SSO', 'BIL', 'IEF', 'LQD' # BAA
]))

def fetch_all_data():
    print("=== 데이터 수집 시작 (DB + API) ===")
    
    db_utils.init_db()
    
    df_cache = {}
    for ticker in ALL_TICKERS:
        try:
            df = tiingo_utils.get_full_history(ticker, start_date='2005-01-01')
            if not df.empty:
                df_cache[ticker] = df
                print(f"[OK] {ticker}: {len(df)} rows (from DB/API)")
            else:
                print(f"[FAIL] {ticker}: No data")
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")
            
    print("[INFO] Fetching FRED Unemployment Rate...")
    try:
        unemployment_df = pdr.get_data_fred('UNRATE', start='2000-01-01', end=datetime.now())
        print(f"[OK] UNRATE: {len(unemployment_df)} rows")
    except Exception as e:
        print(f"[ERROR] UNRATE: {e}")
        unemployment_df = pd.DataFrame()
        
    return df_cache, unemployment_df

def get_next_trading_day(target_date, df_cache):
    """
    target_date가 영업일(데이터 있음)이면 그대로 반환,
    아니면 영업일이 나올 때까지 하루씩 뒤로 이동.
    기준 데이터는 'SPY'를 사용 (미국 휴장일 기준)
    """
    spy_df = df_cache.get('SPY')
    if spy_df is None or spy_df.empty:
        return target_date # 데이터 없으면 그냥 반환 (에러 방지)
        
    curr = target_date
    # 최대 10일까지만 뒤져봄 (장기 휴장 등)
    for _ in range(10):
        # curr가 spy_df 인덱스에 있는지 확인
        # 인덱스는 pd.Timestamp
        ts = pd.Timestamp(curr)
        if ts in spy_df.index:
            return curr
        curr += timedelta(days=1)
        
    return target_date # 못 찾으면 원래 날짜 반환

def get_portfolio_value(holdings, current_cash, current_date, df_cache):
    stock_value = 0.0
    for ticker, qty in holdings.items():
        if qty == 0: continue
        price = tiingo_utils.get_price_at_date(ticker, current_date, df_cache)
        if price is None:
            price = 0
        stock_value += price * qty
    return stock_value + current_cash

def run_backtest():
    df_cache, unemployment_df = fetch_all_data()
    
    # 시작 날짜 설정
    start_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    end_dt = datetime.strptime(END_DATE, '%Y-%m-%d')
    
    # 초기 상태
    current_cash = INITIAL_CAPITAL
    holdings = {} 
    
    history = []
    
    print(f"\n=== 백테스트 시작 ({START_DATE} ~ {END_DATE}) ===")
    print(f"Strategy Weights: BAA {BAA_WEIGHT*100:.0f}% / LAA {LAA_WEIGHT*100:.0f}%")
    
    # 월별 루프를 위한 변수
    # 매월 1일을 기준으로 잡고, get_next_trading_day로 보정
    iter_date = start_dt
    
    while iter_date <= end_dt:
        # 1. 이번 달의 리밸런싱 날짜(영업일) 찾기
        rebal_date = get_next_trading_day(iter_date, df_cache)
        
        # 만약 보정된 날짜가 end_date를 넘어가면 종료
        if rebal_date > end_dt:
            break
            
        # 2. 현재 총 자산 가치 평가
        portfolio_value = get_portfolio_value(holdings, current_cash, rebal_date, df_cache)
            
        # 3. 리밸런싱 수행
        investable_amount = portfolio_value
        
        alloc_baa_amt = investable_amount * BAA_WEIGHT
        alloc_laa_amt = investable_amount * LAA_WEIGHT
        
        try:
            alloc_baa = baa_g4_strategy(alloc_baa_amt, rebal_date, df_cache) if BAA_WEIGHT > 0 else {}
            alloc_laa = laa_strategy(alloc_laa_amt, rebal_date, df_cache, unemployment_df) if LAA_WEIGHT > 0 else {}
        except Exception as e:
            print(f"[ERROR] Strategy execution failed at {rebal_date}")
            traceback.print_exc()
            alloc_baa, alloc_laa = {}, {}

        target_alloc = {}
        for alloc in [alloc_baa, alloc_laa]:
            if not alloc: continue
            for ticker, amount in alloc.items():
                target_alloc[ticker] = target_alloc.get(ticker, 0.0) + amount
                
        new_holdings = {}
        used_cash = 0.0
        
        for ticker, amount in target_alloc.items():
            if amount <= 0: continue
            price = tiingo_utils.get_price_at_date(ticker, rebal_date, df_cache)
            if price and price > 0:
                qty = amount / price 
                new_holdings[ticker] = qty
                used_cash += amount
            else:
                pass
                
        current_cash = investable_amount - used_cash
        holdings = new_holdings
        
        history.append({
            'date': rebal_date,
            'total_value': portfolio_value,
            'cash': current_cash,
            'holdings': str(new_holdings)
        })
        
        # 다음 달 1일로 이동
        # 현재 iter_date가 1월 1일이면 -> 2월 1일로 설정
        # (다음 루프에서 2월 1일의 영업일을 다시 찾음)
        iter_date += relativedelta(months=1)

    # 결과 저장
    res_df = pd.DataFrame(history)
    res_df.set_index('date', inplace=True)
    
    if not res_df.empty:
        start_val = res_df['total_value'].iloc[0]
        end_val = res_df['total_value'].iloc[-1]
        
        days = (res_df.index[-1] - res_df.index[0]).days
        years = days / 365.25
        cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else 0
        
        res_df['peak'] = res_df['total_value'].cummax()
        res_df['dd'] = (res_df['total_value'] - res_df['peak']) / res_df['peak']
        mdd = res_df['dd'].min()
        
        print("\n=== 백테스트 결과 ===")
        print(f"Initial: ${start_val:,.2f}")
        print(f"Final:   ${end_val:,.2f}")
        print(f"CAGR:    {cagr*100:.2f}%")
        print(f"MDD:     {mdd*100:.2f}%")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'backtest_result_{timestamp}.xlsx'
        
        res_df.to_excel(filename)
        print(f"Saved to {filename}")

if __name__ == '__main__':
    run_backtest()
