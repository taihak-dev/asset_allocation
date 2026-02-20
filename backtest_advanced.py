import pandas as pd
import pandas_datareader as pdr
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from utils import tiingo_utils, db_utils
from strategies.baa_strategy import baa_g4_strategy
from strategies.laa_strategy import laa_strategy
import traceback

# 1. 설정
START_DATE = '2010-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')
INITIAL_CAPITAL = 10000 

# 사용되는 모든 티커
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
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")
            
    print("[INFO] Fetching FRED Unemployment Rate...")
    try:
        unemployment_df = pdr.get_data_fred('UNRATE', start='2000-01-01', end=datetime.now())
    except Exception as e:
        unemployment_df = pd.DataFrame()
        
    return df_cache, unemployment_df

def get_portfolio_value(holdings, current_cash, current_date, df_cache):
    stock_value = 0.0
    for ticker, qty in holdings.items():
        if qty == 0: continue
        price = tiingo_utils.get_price_at_date(ticker, current_date, df_cache)
        if price is None: price = 0
        stock_value += price * qty
    return stock_value + current_cash

def run_advanced_backtest(mode='basic'):
    """
    mode:
      - 'basic': 기존 BAA(40)+LAA(60) (월간 리밸런싱만)
      - 'stop_loss': 중간 손절 (-5%) 적용
      - 'dynamic': 동적 비중 조절 적용
      - 'all': 둘 다 적용
    """
    df_cache, unemployment_df = fetch_all_data()
    
    start_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    end_dt = datetime.strptime(END_DATE, '%Y-%m-%d')
    
    current_cash = INITIAL_CAPITAL
    holdings = {} 
    history = []
    
    # 리밸런싱 기준일 (매월 초)
    next_rebal_date = start_dt
    
    # 손절 관련 변수
    last_rebal_value = INITIAL_CAPITAL
    stop_loss_triggered = False
    
    # 일간 루프를 위해 SPY 데이터 기준 날짜 리스트 생성
    spy_df = df_cache.get('SPY')
    if spy_df is None: return
    
    # start_dt 이후의 모든 영업일
    trading_days = spy_df.index[spy_df.index >= pd.Timestamp(start_dt)].tolist()
    trading_days = [d for d in trading_days if d <= pd.Timestamp(end_dt)]
    
    print(f"\n=== Advanced Backtest ({mode}) 시작 ===")
    
    for current_date in trading_days:
        # Timestamp -> datetime 변환
        curr_dt = current_date.to_pydatetime()
        
        # 1. 현재 가치 평가
        portfolio_value = get_portfolio_value(holdings, current_cash, curr_dt, df_cache)
        
        # 2. 리밸런싱 날짜인지 확인 (매월 첫 영업일)
        # 간단히: 월이 바뀌었으면 리밸런싱
        is_rebal_day = False
        if curr_dt >= next_rebal_date:
            is_rebal_day = True
            # 다음달 1일로 설정 (실제 영업일 보정은 루프에서 자동 처리됨)
            next_rebal_date = (curr_dt.replace(day=1) + relativedelta(months=1))
            
        # 3. [전략 1] 중간 손절 체크 (Stop Loss)
        if mode in ['stop_loss', 'all'] and not is_rebal_day and not stop_loss_triggered:
            # 전월 말(직전 리밸런싱) 대비 -5% 하락 시
            if portfolio_value < last_rebal_value * 0.95:
                # 전량 매도
                # print(f"[STOP LOSS] {curr_dt.date()} Value: ${portfolio_value:,.2f} (Drop > 5%)")
                current_cash = portfolio_value
                holdings = {}
                stop_loss_triggered = True
                
        # 4. 리밸런싱 수행
        if is_rebal_day:
            # 손절 상태 해제 (새 달이 시작되면 다시 진입)
            stop_loss_triggered = False
            last_rebal_value = portfolio_value
            
            investable_amount = portfolio_value
            
            # [전략 2] 동적 비중 조절 (Dynamic Weighting)
            baa_weight = 0.4 # 기본값
            laa_weight = 0.6
            
            if mode in ['dynamic', 'all']:
                # BAA가 공격 자산을 선택했는지 미리 확인
                # 가상으로 BAA 실행해봄
                temp_alloc = baa_g4_strategy(100, curr_dt, df_cache)
                selected_asset = list(temp_alloc.keys())[0] if temp_alloc else None
                
                # 공격 자산: QLD, SSO, EFA, EEM
                offensive_list = ['QLD', 'SSO', 'EFA', 'EEM']
                
                if selected_asset in offensive_list:
                    # 공격장: BAA 100%
                    baa_weight = 0.8
                    laa_weight = 0.2
                else:
                    # 수비장: BAA 50% / LAA 50%
                    baa_weight = 0.5
                    laa_weight = 0.5
            
            # 실제 할당
            alloc_baa_amt = investable_amount * baa_weight
            alloc_laa_amt = investable_amount * laa_weight
            
            try:
                alloc_baa = baa_g4_strategy(alloc_baa_amt, curr_dt, df_cache) if baa_weight > 0 else {}
                alloc_laa = laa_strategy(alloc_laa_amt, curr_dt, df_cache, unemployment_df) if laa_weight > 0 else {}
            except:
                alloc_baa, alloc_laa = {}, {}

            target_alloc = {}
            for alloc in [alloc_baa, alloc_laa]:
                if not alloc: continue
                for ticker, amount in alloc.items():
                    target_alloc[ticker] = target_alloc.get(ticker, 0.0) + amount
            
            # 매수
            new_holdings = {}
            used_cash = 0.0
            for ticker, amount in target_alloc.items():
                if amount <= 0: continue
                price = tiingo_utils.get_price_at_date(ticker, curr_dt, df_cache)
                if price and price > 0:
                    qty = amount / price 
                    new_holdings[ticker] = qty
                    used_cash += amount
            
            current_cash = investable_amount - used_cash
            holdings = new_holdings
            
        # 기록 (일간)
        history.append({
            'date': curr_dt,
            'total_value': portfolio_value
        })

    # 결과 분석
    res_df = pd.DataFrame(history)
    res_df.set_index('date', inplace=True)
    
    start_val = res_df['total_value'].iloc[0]
    end_val = res_df['total_value'].iloc[-1]
    
    days = (res_df.index[-1] - res_df.index[0]).days
    years = days / 365.25
    cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else 0
    
    res_df['peak'] = res_df['total_value'].cummax()
    res_df['dd'] = (res_df['total_value'] - res_df['peak']) / res_df['peak']
    mdd = res_df['dd'].min()
    
    print(f"[{mode.upper()}] CAGR: {cagr*100:.2f}% | MDD: {mdd*100:.2f}% | Final: ${end_val:,.2f}")
    
    return res_df

if __name__ == '__main__':
    # 4가지 케이스 비교 실행
    modes = ['basic', 'stop_loss', 'dynamic', 'all']
    results = {}
    
    for m in modes:
        results[m] = run_advanced_backtest(m)
        
    # 결과 저장 (엑셀에 시트별로 저장)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f'advanced_test_{timestamp}.xlsx'
    
    with pd.ExcelWriter(filename) as writer:
        for m, df in results.items():
            df.to_excel(writer, sheet_name=m)
            
    print(f"\nSaved detailed results to {filename}")
