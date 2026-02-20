import pandas as pd
from utils.tiingo_utils import get_iex_last_price
from functools import lru_cache

from datetime import datetime, timedelta
# from strategies.dual_momentum_strategy import original_dual_momentum_strategy
# from strategies.vaa_strategy import vaa_aggressive_strategy, get_return_at_date, calculate_momentum_score_at_date
from strategies.laa_strategy import laa_strategy
from strategies.baa_strategy import baa_g4_strategy, calculate_13612w_score
import os

EXCEL_FILE_PREFIX = 'asset_allocation_results'
SUMMARY_SHEET = 'Portfolio Summary'
DETAILS_SHEET = 'Strategy Details'

# 전략 설명을 전역 변수로 정의
strategy_descriptions = {
    'LAA': {
        'IWD': '미국 대형주',
        'QQQM': '나스닥',
        'GLD': '금',
        'IEF': '미국 중기 국채',
        'SHY': '미국 단기 국채'
    },
    'BAA': {
        'QLD': '나스닥 2배 레버리지',
        'SSO': 'S&P500 2배 레버리지',
        'EFA': '선진국 주식',
        'EEM': '신흥국 주식',
        'BIL': '미국 초단기 국채',
        'IEF': '미국 중기 국채',
        'LQD': '미국 회사채',
        'AGG': '미국 혼합 채권'
    }
}


def save_to_excel(df, sheet_name, file_name=None):
    today = datetime.now().strftime("%y%m%d")

    if not os.path.exists('result'):
        os.makedirs('result')

    if file_name is None:
        file_name = f"{today}_{EXCEL_FILE_PREFIX}.xlsx"
    else:
        file_name = f"{today}_{file_name}"

    file_path = os.path.join('result', file_name)

    with pd.ExcelWriter(file_path, engine='openpyxl', mode='a' if os.path.exists(file_path) else 'w') as writer:
        if os.path.exists(file_path) and sheet_name in writer.book.sheetnames:
            idx = writer.book.sheetnames.index(sheet_name)
            writer.book.remove(writer.book.worksheets[idx])
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"Saved {sheet_name} to {file_path}")
    return file_path

@lru_cache(maxsize=None)
def get_current_price(ticker):
    info = get_iex_last_price(ticker)
    if isinstance(info, list):
        info = info[0] if info else {}
    if isinstance(info, (int, float)):
        return info
    if isinstance(info, dict):
        return info.get('tngoLast') or info.get('last') or 0
    return 0


def update_summary_sheet(new_value, allocations, file_name=None):
    # 1) 전체 티커별 할당 금액 집계
    total_alloc = {}
    for alloc in allocations.values():
        if isinstance(alloc, dict):
            for t, amt in alloc.items():
                total_alloc[t] = total_alloc.get(t, 0) + amt

    # 2) 현재 가격 조회 및 각 행(row) 생성
    rows = []
    now = datetime.now()
    for ticker, amt in total_alloc.items():
        price = get_current_price(ticker)
        qty   = int(amt / price) if price > 0 else 0
        rows.append({
            '리밸런싱 일자': now,
            '자산 가치':     new_value,
            'Ticker':       ticker,
            '수량':         qty,
            '금액':         amt
        })

    # 3) DataFrame 생성 후 저장
    df_sum = pd.DataFrame(rows)
    return save_to_excel(df_sum, SUMMARY_SHEET, file_name)



def update_strategy_details_sheet(allocations, total_asset_value, file_name=None):
    rows = []
    now = datetime.now()
    
    for strategy, alloc in allocations.items():
        if not isinstance(alloc, dict):
            continue
        strat_total = sum(alloc.values())
        for ticker, amt in alloc.items():
            price = get_current_price(ticker)
            qty   = int(amt / price) if price > 0 else 0
            desc  = strategy_descriptions.get(strategy, {}).get(ticker, '')
            row = {
                'Strategy': strategy,
                'Description': desc,
                'Ticker': ticker,
                'Price': price,
                'Assets': amt,
                'Quantity': qty,
                'Ratio': (amt/strat_total)*100 if strat_total else 0,
                'Strategy ratio': (strat_total/total_asset_value)*100,
                'Final ratio': (amt/total_asset_value)*100
            }
            
            # 상세 지표 추가
            if strategy == 'BAA':
                row['Score'] = calculate_13612w_score(ticker, now)
                
            rows.append(row)
    df_det = pd.DataFrame(rows)
    return save_to_excel(df_det, DETAILS_SHEET, file_name)


def main():
    # initial investments 입력
    raw = input("Enter your initial investment amounts (comma-separated): ")
    investments = [float(x.strip()) for x in raw.split(',') if x.strip()]

    for idx, total_value in enumerate(investments, start=1):
        print(f"\n=== Account {idx}: ${total_value:.2f} ===")
        # 전략 할당 (2등분: BAA 50%, LAA 50%)
        allocs = {
            'BAA': baa_g4_strategy(total_value * 0.5),
            'LAA': laa_strategy(total_value * 0.5)
        }
        # 파일명에 계정 번호 포함
        file_name = f"account{idx}_{EXCEL_FILE_PREFIX}.xlsx"
        update_summary_sheet(total_value, allocs, file_name)
        update_strategy_details_sheet(allocs, total_value, file_name)
        print(f"Finished account {idx}, results in 'result/{file_name}'")

if __name__ == '__main__':
    main()
