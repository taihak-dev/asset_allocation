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
    
    is_rebalancing_day = (datetime.now().day == 1)
    
    msg = f"📅 [{today_str}] 자산 배분 봇 리포트\n\n"
    
    if is_rebalancing_day:
        msg += "🔔 **리밸런싱 알림** 🔔\n"
        msg += f"전략: {config.STRATEGY_TYPE}\n\n"
        
        # 1. 현재 포트폴리오 평가
        current_holdings = portfolio.get('holdings', {})
        total_eval_value = float(portfolio['cash'])
        for krx_code, qty in current_holdings.items():
            price = krx_utils.get_krx_price(krx_code)
            if price:
                total_eval_value += float(price) * int(qty)
        
        msg += f"💰 총 자산(평가액): {total_eval_value:,.0f}원\n\n"
        
        # 2. 목표 포트폴리오 계산
        target_weights = get_strategy_allocation()
        target_holdings = {} # {krx_code: qty}
        
        for us_ticker, weight in target_weights.items():
            if weight <= 0: continue
            krx_code = config.TICKER_MAP.get(us_ticker)
            if not krx_code: continue
            
            price = krx_utils.get_krx_price(krx_code)
            if price:
                target_amount = total_eval_value * weight
                qty = int(target_amount / price)
                if qty > 0:
                    target_holdings[krx_code] = target_holdings.get(krx_code, 0) + qty

        # 3. 매매 지시 생성 (기존 vs 목표)
        all_codes = set(current_holdings.keys()) | set(target_holdings.keys())
        
        trades_sell = []
        trades_buy = []
        trades_hold = []
        
        for code in sorted(list(all_codes)):
            current_qty = current_holdings.get(code, 0)
            target_qty = target_holdings.get(code, 0)
            name = config.KRX_NAME_MAP.get(code, code)
            
            if target_qty > current_qty:
                trades_buy.append(f"- {name}: {target_qty - current_qty}주 매수")
            elif target_qty < current_qty:
                trades_sell.append(f"- {name}: {current_qty - target_qty}주 매도")
            elif target_qty > 0:
                trades_hold.append(f"- {name}: {target_qty}주 보유")

        # 4. 메시지 조합
        if trades_sell:
            msg += "[🔴 매도 목록]\n" + "\n".join(trades_sell) + "\n\n"
        if trades_buy:
            msg += "[🔵 매수 목록]\n" + "\n".join(trades_buy) + "\n\n"
        if trades_hold:
            msg += "[⚪️ 보유 목록]\n" + "\n".join(trades_hold) + "\n\n"
            
        msg += "👉 위 지시대로 매매 후, 실제 체결가로 portfolio.json을 수정해주세요!"
        
        # 포트폴리오 파일은 실제 매매 후 수동 업데이트하므로 봇이 수정하지 않음.
        
    else:
        # 데일리 리포트 (기존과 동일)
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
        total_profit_real = total_asset - config.INITIAL_CAPITAL_KRW
        total_profit_pct = (total_profit_real / config.INITIAL_CAPITAL_KRW) * 100
        
        msg += "\n"
        msg += f"💰 총 자산: {total_asset:,.0f}원\n"
        msg += f"💵 현금: {cash:,.0f}원\n"
        msg += f"📈 총 수익: {total_profit_real:+,.0f}원 ({total_profit_pct:+.2f}%)"
        
    telegram_utils.send_message(msg)

if __name__ == '__main__':
    run_bot()
