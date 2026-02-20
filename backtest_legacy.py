import pandas as pd
import pandas_datareader as pdr
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from utils import tiingo_utils, db_utils
from strategies.dual_momentum_strategy import original_dual_momentum_strategy
from strategies.vaa_strategy import vaa_aggressive_strategy
from strategies.laa_strategy import laa_strategy
import traceback

# 1. 설정
START_DATE = '2010-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')
INITIAL_CAPITAL = 10000 

# 전략 비중 (3등분)
ODM_WEIGHT = 1/3
VAA_WEIGHT = 1/3
LAA_WEIGHT = 1/3

# 사용되는 모든 티커 (ODM + VAA + LAA)
ALL_TICKERS = list(set([
    'VOO', 'EFA', 'AGG', 'BIL', # ODM
    'VOO', 'EFA', 'VWO', 'AGG', 'LQD', 'IEF', 'SHY', # VAA
    'IWD', 'GLD', 'IEF', 'QQQM', 'SHY', 'SPY' # LAA
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
                print(f"[OK] {ticker}: {len(df)} rows")
            else:
                print(f"[FAIL] {ticker}: No data")
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")
            
    fred_cache = {}
    print("[INFO] Fetching FRED Data (UNRATE)...")
    try:
        unrate = pdr.get_data_fred('UNRATE', start='2000-01-01', end=datetime.now())
        fred_cache['UNRATE'] = unrate
        print(f"[OK] UNRATE: {len(unrate)} rows")
    except Exception as e:
        print(f"[ERROR] FRED Data: {e}")
        
    return df_cache, fred_cache

def get_next_trading_day(target_date, df_cache):
    spy_df = df_cache.get('SPY')
    if spy_df is None or spy_df.empty:
        return target_date
        
    curr = target_date
    for _ in range(10):
        ts = pd.Timestamp(curr)
        if ts in spy_df.index:
            return curr
        curr += timedelta(days=1)
    return target_date

def get_portfolio_value(holdings, current_cash, current_date, df_cache):
    stock_value = 0.0
    for ticker, qty in holdings.items():
        if qty == 0: continue
        price = tiingo_utils.get_price_at_date(ticker, current_date, df_cache)
        if price is None:
            price = 0
        stock_value += price * qty
    return stock_value + current_cash

def analyze_results(df):
    print("\n=== 백테스트 상세 분석 리포트 ===")
    
    start_val = df['total_value'].iloc[0]
    end_val = df['total_value'].iloc[-1]
    total_return = (end_val / start_val) - 1
    
    days = (df.index[-1] - df.index[0]).days
    years = days / 365.25
    cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else 0
    
    df['peak'] = df['total_value'].cummax()
    df['dd'] = (df['total_value'] - df['peak']) / df['peak']
    mdd = df['dd'].min()
    mdd_date = df['dd'].idxmin()
    
    print(f"1. 종합 성과")
    print(f"   - 초기 자본: ${start_val:,.2f}")
    print(f"   - 최종 자본: ${end_val:,.2f}")
    print(f"   - 총 수익률: {total_return*100:.2f}%")
    print(f"   - 연평균 수익률 (CAGR): {cagr*100:.2f}%")
    print(f"   - 최대 낙폭 (MDD): {mdd*100:.2f}% (발생일: {mdd_date.strftime('%Y-%m-%d')})")
    
    print(f"\n2. 연도별 수익률")
    df['year'] = df.index.year
    yearly_returns = df.groupby('year')['total_value'].apply(lambda x: (x.iloc[-1] / x.iloc[0]) - 1)
    
    for year, ret in yearly_returns.items():
        print(f"   - {year}년: {ret*100:.2f}%")
        
    df['monthly_ret'] = df['total_value'].pct_change()
    best_month = df['monthly_ret'].max()
    worst_month = df['monthly_ret'].min()
    win_rate = (df['monthly_ret'] > 0).mean()
    
    print(f"\n3. 월별 통계")
    print(f"   - 최고 월 수익률: {best_month*100:.2f}%")
    print(f"   - 최악 월 수익률: {worst_month*100:.2f}%")
    print(f"   - 승률 (월간 상승 확률): {win_rate*100:.2f}%")
    
    avg_cash_ratio = (df['cash'] / df['total_value']).mean()
    max_cash_ratio = (df['cash'] / df['total_value']).max()
    
    print(f"\n4. 포트폴리오 구성")
    print(f"   - 평균 현금 비중: {avg_cash_ratio*100:.2f}%")
    print(f"   - 최대 현금 비중: {max_cash_ratio*100:.2f}%")

def run_backtest():
    df_cache, fred_cache = fetch_all_data()
    unemployment_df = fred_cache.get('UNRATE', pd.DataFrame())
    
    start_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    end_dt = datetime.strptime(END_DATE, '%Y-%m-%d')
    
    current_cash = INITIAL_CAPITAL
    holdings = {} 
    history = []
    
    print(f"\n=== Legacy 백테스트 시작 ({START_DATE} ~ {END_DATE}) ===")
    print(f"Weights: ODM 33.3% / VAA 33.3% / LAA 33.3%")
    
    iter_date = start_dt
    
    while iter_date <= end_dt:
        rebal_date = get_next_trading_day(iter_date, df_cache)
        if rebal_date > end_dt: break
            
        portfolio_value = get_portfolio_value(holdings, current_cash, rebal_date, df_cache)
        investable_amount = portfolio_value
        
        alloc_odm_amt = investable_amount * ODM_WEIGHT
        alloc_vaa_amt = investable_amount * VAA_WEIGHT
        alloc_laa_amt = investable_amount * LAA_WEIGHT
        
        try:
            alloc_odm = original_dual_momentum_strategy(alloc_odm_amt, rebal_date, df_cache)
            alloc_vaa = vaa_aggressive_strategy(alloc_vaa_amt, rebal_date, df_cache)
            # LAA는 기본 설정 (Smart Bond 미사용)
            alloc_laa = laa_strategy(alloc_laa_amt, rebal_date, df_cache, unemployment_df)
        except Exception as e:
            print(f"[ERROR] Strategy execution failed at {rebal_date}")
            traceback.print_exc()
            alloc_odm, alloc_vaa, alloc_laa = {}, {}, {}

        target_alloc = {}
        for alloc in [alloc_odm, alloc_vaa, alloc_laa]:
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
        
        iter_date += relativedelta(months=1)

    res_df = pd.DataFrame(history)
    res_df.set_index('date', inplace=True)
    
    if not res_df.empty:
        analyze_results(res_df)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'backtest_legacy_result_{timestamp}.xlsx'
        
        res_df.to_excel(filename)
        print(f"Saved to {filename}")

if __name__ == '__main__':
    run_backtest()
