import os
import json
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

import config
from utils import tiingo_utils, krx_utils, telegram_utils, db_utils
from strategies.protocol20_strategy import protocol20_strategy
from strategies.laa_strategy import laa_strategy
import pandas_datareader as pdr

PORTFOLIO_FILE = 'portfolio.json'

def load_portfolio():
    """
    포트폴리오 파일 로드 (파일이 없거나 깨졌으면 초기화)
    """
    default_portfolio = {'cash': config.INITIAL_CAPITAL_KRW, 'holdings': {}, 'last_rebal_date': ''}
    
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, 'r') as f:
                # 파일이 비어있는지 확인
                content = f.read().strip()
                if not content:
                    return default_portfolio
                return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[WARN] Failed to load portfolio ({e}). Initializing new portfolio.")
            return default_portfolio
            
    return default_portfolio

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=4)

def get_strategy_allocation():
    """
    현재 날짜 기준으로 전략적 자산 배분 비율 계산 (미국 티커 기준)
    """
    # 데이터 준비
    db_utils.init_db()
    
    # 필요한 티커들 (config.TICKER_MAP의 키)
    us_tickers = list(config.TICKER_MAP.keys())
    
    df_cache = {}
    for t in us_tickers:
        try:
            df = tiingo_utils.get_full_history(t)
            if not df.empty: df_cache[t] = df
        except: pass
        
    fred_cache = {}
    try:
        unrate = pdr.get_data_fred('UNRATE', start='2000-01-01')
        fred_cache['UNRATE'] = unrate
        vix = pdr.get_data_fred('VIXCLS', start='2000-01-01')
        vix.columns = ['value']
        fred_cache['VIXCLS'] = vix
        dgs10 = pdr.get_data_fred('DGS10', start='2000-01-01')
        dgs10.columns = ['value']
        fred_cache['DGS10'] = dgs10
    except: pass
    
    # 전략 실행
    now = datetime.now()
    
    if config.STRATEGY_TYPE == 'GROWTH':
        # P20 (80%) + LAA (20%)
        p20_alloc = protocol20_strategy(0.8, now, df_cache, fred_cache, vix_threshold=30.0)
        laa_alloc = laa_strategy(0.2, now, df_cache, fred_cache.get('UNRATE'), fred_cache.get('DGS10'), use_smart_bond=True)
    else:
        # BALANCED: BAA (40%) + LAA (60%) - BAA 로직은 P20 함수 재사용하되 VIX Gate 끔(혹은 높게)
        # 여기서는 편의상 P20 함수를 쓰되 비중을 조절
        p20_alloc = protocol20_strategy(0.4, now, df_cache, fred_cache, vix_threshold=999.0) # VIX 무시
        laa_alloc = laa_strategy(0.6, now, df_cache, fred_cache.get('UNRATE'), fred_cache.get('DGS10'), use_smart_bond=True)
        
    # 합산
    final_alloc = {}
    for alloc in [p20_alloc, laa_alloc]:
        for ticker, weight in alloc.items():
            final_alloc[ticker] = final_alloc.get(ticker, 0.0) + weight
            
    return final_alloc

def run_bot():
    portfolio = load_portfolio()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # [원상복구] 매월 1일에만 리밸런싱 실행
    is_rebalancing_day = (datetime.now().day == 1)
    
    msg = f"📅 [{today_str}] 자산 배분 봇 리포트\n\n"
    
    if is_rebalancing_day:
        msg += "🔔 **리밸런싱 알림** 🔔\n"
        msg += f"전략: {config.STRATEGY_TYPE}\n\n"
        
        # 1) 목표 비중 계산
        target_weights = get_strategy_allocation()
        
        # 2) 한국 티커로 변환 및 매수 수량 계산
        # 현재 총 자산 가치 (현금 + 보유주식 평가액)
        total_value = float(portfolio['cash']) # float 변환
        for krx_code, qty in portfolio['holdings'].items():
            price = krx_utils.get_krx_price(krx_code)
            if price:
                total_value += float(price) * int(qty)
                
        msg += f"💰 총 자산: {total_value:,.0f}원\n\n"
        msg += "[매매 목표]\n"
        
        new_holdings = {}
        used_cash = 0.0
        
        for us_ticker, weight in target_weights.items():
            if weight <= 0: continue
            
            krx_code = config.TICKER_MAP.get(us_ticker)
            if not krx_code:
                msg += f"⚠️ {us_ticker}: 매핑된 한국 종목 없음 (건너뜀)\n"
                continue
                
            krx_name = config.KRX_NAME_MAP.get(krx_code, krx_code)
            target_amount = total_value * weight
            price = krx_utils.get_krx_price(krx_code)
            
            if price:
                # [수정] JSON 저장을 위해 int(), float() 명시적 변환
                qty = int(target_amount / price)
                amount = float(qty * price)
                
                if qty > 0:
                    msg += f"- {krx_name}: {qty}주 ({amount:,.0f}원)\n"
                    new_holdings[krx_code] = qty
                    used_cash += amount
            else:
                msg += f"⚠️ {krx_name}: 현재가 조회 실패\n"
        
        # 포트폴리오 업데이트 (가상 체결)
        portfolio['holdings'] = new_holdings
        portfolio['cash'] = float(total_value - used_cash) # float 변환
        portfolio['last_rebal_date'] = today_str
        save_portfolio(portfolio)
        
        msg += f"\n잔여 현금: {portfolio['cash']:,.0f}원\n"
        msg += "👉 위 수량대로 MTS에서 매매하세요!"
        
    else:
        # 2. 데일리 리포트
        msg += "📊 **데일리 포트폴리오 현황**\n\n"
        
        total_eval = float(portfolio['cash'])
        invest_eval = 0.0
        
        for krx_code, qty in portfolio['holdings'].items():
            price = krx_utils.get_krx_price(krx_code)
            krx_name = config.KRX_NAME_MAP.get(krx_code, krx_code)
            
            if price:
                val = float(price) * int(qty)
                invest_eval += val
                msg += f"- {krx_name}: {qty}주 ({val:,.0f}원)\n"
            else:
                msg += f"- {krx_name}: 가격 조회 실패\n"
                
        total_asset = total_eval + invest_eval
        profit = total_asset - config.INITIAL_CAPITAL_KRW
        profit_rate = (profit / config.INITIAL_CAPITAL_KRW) * 100
        
        msg += f"\n💰 총 자산: {total_asset:,.0f}원"
        msg += f"\n📈 수익: {profit:,.0f}원 ({profit_rate:.2f}%)"
        
    # 텔레그램 발송
    telegram_utils.send_message(msg)

if __name__ == '__main__':
    run_bot()
