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
    # [수정] avg_prices 필드 추가
    default_portfolio = {
        'cash': config.INITIAL_CAPITAL_KRW, 
        'holdings': {}, 
        'last_rebal_date': '',
        'avg_prices': {} 
    }
    
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, 'r') as f:
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
    db_utils.init_db()
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
    
    now = datetime.now()
    
    if config.STRATEGY_TYPE == 'GROWTH':
        p20_alloc = protocol20_strategy(0.8, now, df_cache, fred_cache, vix_threshold=30.0)
        laa_alloc = laa_strategy(0.2, now, df_cache, fred_cache.get('UNRATE'), fred_cache.get('DGS10'), use_smart_bond=True)
    else:
        p20_alloc = protocol20_strategy(0.4, now, df_cache, fred_cache, vix_threshold=999.0) 
        laa_alloc = laa_strategy(0.6, now, df_cache, fred_cache.get('UNRATE'), fred_cache.get('DGS10'), use_smart_bond=True)
        
    final_alloc = {}
    for alloc in [p20_alloc, laa_alloc]:
        for ticker, weight in alloc.items():
            final_alloc[ticker] = final_alloc.get(ticker, 0.0) + weight
            
    return final_alloc

def run_bot():
    portfolio = load_portfolio()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # 매월 1일에만 리밸런싱 실행
    is_rebalancing_day = (datetime.now().day == 1)
    
    msg = f"📅 [{today_str}] 자산 배분 봇 리포트\n\n"
    
    if is_rebalancing_day:
        msg += "🔔 **리밸런싱 알림** 🔔\n"
        msg += f"전략: {config.STRATEGY_TYPE}\n\n"
        
        target_weights = get_strategy_allocation()
        
        # 현재 총 자산 가치 재계산 (최신가 반영)
        total_eval_value = float(portfolio['cash'])
        for krx_code, qty in portfolio['holdings'].items():
            price = krx_utils.get_krx_price(krx_code)
            if price:
                total_eval_value += float(price) * int(qty)
        
        msg += f"💰 총 자산(평가액): {total_eval_value:,.0f}원\n\n"
        msg += "[매매 목표]\n"
        
        new_holdings = {}
        new_avg_prices = {} # 리밸런싱 직후엔 평단가를 전일 종가로 가정 (실제 매수 후 수정 필요)
        used_cash = 0.0
        
        for us_ticker, weight in target_weights.items():
            if weight <= 0: continue
            
            krx_code = config.TICKER_MAP.get(us_ticker)
            if not krx_code:
                msg += f"⚠️ {us_ticker}: 매핑된 한국 종목 없음\n"
                continue
                
            krx_name = config.KRX_NAME_MAP.get(krx_code, krx_code)
            target_amount = total_eval_value * weight
            price = krx_utils.get_krx_price(krx_code)
            
            if price:
                qty = int(target_amount / price)
                amount = float(qty * price)
                
                if qty > 0:
                    msg += f"- {krx_name}: {qty}주 ({amount:,.0f}원)\n"
                    new_holdings[krx_code] = qty
                    new_avg_prices[krx_code] = float(price) # 임시 평단가
                    used_cash += amount
            else:
                msg += f"⚠️ {krx_name}: 현재가 조회 실패\n"
        
        portfolio['holdings'] = new_holdings
        portfolio['avg_prices'] = new_avg_prices # 평단가 초기화
        portfolio['cash'] = float(total_eval_value - used_cash)
        portfolio['last_rebal_date'] = today_str
        save_portfolio(portfolio)
        
        msg += f"\n잔여 현금: {portfolio['cash']:,.0f}원\n"
        msg += "👉 MTS 매매 후, 실제 체결가로 portfolio.json을 수정해주세요!"
        
    else:
        # 2. 데일리 리포트 (수익률 포함)
        msg += "📊 **데일리 포트폴리오 현황**\n"
        
        cash = float(portfolio['cash'])
        invest_eval = 0.0
        total_profit = 0.0
        
        avg_prices = portfolio.get('avg_prices', {})
        
        for krx_code, qty in portfolio['holdings'].items():
            qty = int(qty)
            price = krx_utils.get_krx_price(krx_code)
            krx_name = config.KRX_NAME_MAP.get(krx_code, krx_code)
            
            if price:
                price = float(price)
                val = price * qty
                invest_eval += val
                
                # 수익률 계산
                avg_price = float(avg_prices.get(krx_code, 0))
                if avg_price > 0:
                    profit = (price - avg_price) * qty
                    profit_pct = ((price - avg_price) / avg_price) * 100
                    total_profit += profit
                    emoji = "🔴" if profit > 0 else "🔵"
                    msg += f"- {krx_name}: {qty}주 | {profit_pct:+.2f}% ({profit:+,.0f}원) {emoji}\n"
                else:
                    msg += f"- {krx_name}: {qty}주 ({val:,.0f}원)\n"
            else:
                msg += f"- {krx_name}: 가격 조회 실패\n"
                
        total_asset = cash + invest_eval
        # 총 수익 = (현재 총자산) - (초기 투자금) -> (X)
        # 총 수익 = (평가손익 합계) -> (O) 이미 실현손익이 cash에 반영되어 있으므로 애매함.
        # 가장 정확한 건: (현재 총자산) - (입금 총액). 입금액 관리가 안되므로
        # 여기서는 '이번 리밸런싱 이후의 평가 손익'을 보여주는게 나음.
        # 또는 단순히 (현재 총자산)을 보여주고 전일 대비 등을 보여주는게 좋음.
        
        # 여기서는 config.INITIAL_CAPITAL_KRW 대비 수익률로 표시 (원금 불변 가정)
        total_profit_real = total_asset - config.INITIAL_CAPITAL_KRW
        total_profit_pct = (total_profit_real / config.INITIAL_CAPITAL_KRW) * 100
        
        msg += "\n"
        msg += f"💰 총 자산: {total_asset:,.0f}원\n"
        msg += f"💵 현금: {cash:,.0f}원\n"
        msg += f"📈 총 수익: {total_profit_real:+,.0f}원 ({total_profit_pct:+.2f}%)"
        
    # 텔레그램 발송
    telegram_utils.send_message(msg)

if __name__ == '__main__':
    run_bot()
