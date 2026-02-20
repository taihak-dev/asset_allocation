import pandas as pd
import pandas_datareader as pdr
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from utils import tiingo_utils, db_utils
from strategies.protocol20_strategy import protocol20_strategy
from strategies.laa_strategy import laa_strategy
import traceback
import numpy as np

# ==============================================================================
# [설정 영역] 투자 성향에 맞춰 아래 값들을 조절하세요.
# ==============================================================================

# 1. 백테스트 기간 설정
# ------------------------------------------------------------------------------
# 언제부터 언제까지의 데이터로 테스트할지 결정합니다.
# START_DATE: 시작일 (예: '2010-01-01')
# END_DATE: 종료일 (보통 오늘 날짜로 자동 설정됨)
START_DATE = '2010-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')

# 2. 초기 투자금
# ------------------------------------------------------------------------------
# 테스트를 시작할 때의 원금입니다. (단위: 달러)
INITIAL_CAPITAL = 10000 

# 3. 전략 비중 설정 (합계가 1.0이 되도록 설정)
# ------------------------------------------------------------------------------
# P20_WEIGHT: 공격형 전략(Protocol 20)의 비중. 높을수록 수익 추구.
# LAA_WEIGHT: 수비형 전략(LAA)의 비중. 높을수록 안정성 추구.
# (추천) 공격적: P20 0.8 / LAA 0.2
# (추천) 균형적: P20 0.5 / LAA 0.5
P20_WEIGHT = 0.8
LAA_WEIGHT = 0.2

# 4. [튜닝] VIX 임계값 (공포 지수 민감도)
# ------------------------------------------------------------------------------
# 시장의 공포 지수(VIX)가 이 값보다 높으면, 레버리지(2배수) 투자를 멈추고 1배수로 전환합니다.
# - 20.0: 보수적 설정. 조금만 불안해도 안전하게 갑니다. (수익률 낮아질 수 있음)
# - 30.0: 공격적 설정. 웬만한 공포는 무시하고 수익을 추구합니다. (MDD 커질 수 있음)
VIX_THRESHOLD = 30.0 

# 5. [튜닝] 스마트 채권 (Smart Bond) 사용 여부
# ------------------------------------------------------------------------------
# 금리가 오르는 시기(채권 가격 하락기)에 채권(IEF) 대신 현금(BIL)을 보유할지 결정합니다.
# - True: 사용함. 2022년 같은 금리 급등기에 방어력이 좋아집니다. (추천)
# - False: 사용 안 함. 기존 방식대로 무조건 채권을 보유합니다.
USE_SMART_BOND = True

# ==============================================================================

# 사용되는 모든 티커
ALL_TICKERS = list(set([
    'IWD', 'GLD', 'IEF', 'QQQM', 'SHY', 'SPY', # LAA
    'SPY', 'EFA', 'EEM', 'AGG', 'QLD', 'SSO', 'BIL', 'IEF', 'LQD', 'QQQM' # Protocol 20
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
    print("[INFO] Fetching FRED Data (UNRATE, VIX, DGS10)...")
    try:
        unrate = pdr.get_data_fred('UNRATE', start='2000-01-01', end=datetime.now())
        fred_cache['UNRATE'] = unrate
        print(f"[OK] UNRATE: {len(unrate)} rows")
        
        vix = pdr.get_data_fred('VIXCLS', start='2000-01-01', end=datetime.now())
        vix.columns = ['value']
        fred_cache['VIXCLS'] = vix
        print(f"[OK] VIXCLS: {len(vix)} rows")
        
        dgs10 = pdr.get_data_fred('DGS10', start='2000-01-01', end=datetime.now())
        dgs10.columns = ['value']
        fred_cache['DGS10'] = dgs10
        print(f"[OK] DGS10: {len(dgs10)} rows")
        
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
    dgs10_df = fred_cache.get('DGS10', pd.DataFrame())
    
    start_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    end_dt = datetime.strptime(END_DATE, '%Y-%m-%d')
    
    current_cash = INITIAL_CAPITAL
    holdings = {} 
    history = []
    
    print(f"\n=== Protocol 20 백테스트 시작 ({START_DATE} ~ {END_DATE}) ===")
    print(f"Weights: Protocol20 {P20_WEIGHT*100:.0f}% / LAA {LAA_WEIGHT*100:.0f}%")
    print(f"VIX Threshold: {VIX_THRESHOLD}")
    print(f"Smart Bond: {USE_SMART_BOND}")
    
    iter_date = start_dt
    
    while iter_date <= end_dt:
        rebal_date = get_next_trading_day(iter_date, df_cache)
        if rebal_date > end_dt: break
            
        portfolio_value = get_portfolio_value(holdings, current_cash, rebal_date, df_cache)
        investable_amount = portfolio_value
        
        alloc_p20_amt = investable_amount * P20_WEIGHT
        alloc_laa_amt = investable_amount * LAA_WEIGHT
        
        try:
            alloc_p20 = protocol20_strategy(alloc_p20_amt, rebal_date, df_cache, fred_cache, vix_threshold=VIX_THRESHOLD)
            # Smart Bond 설정 전달
            alloc_laa = laa_strategy(alloc_laa_amt, rebal_date, df_cache, unemployment_df, dgs10_df, use_smart_bond=USE_SMART_BOND)
        except Exception as e:
            print(f"[ERROR] Strategy execution failed at {rebal_date}")
            traceback.print_exc()
            alloc_p20, alloc_laa = {}, {}

        target_alloc = {}
        for alloc in [alloc_p20, alloc_laa]:
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
        filename = f'backtest_p20_result_{timestamp}.xlsx'
        
        res_df.to_excel(filename)
        print(f"Saved to {filename}")

if __name__ == '__main__':
    run_backtest()
