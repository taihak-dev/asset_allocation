import pandas as pd
import numpy as np
import sys

# 명령행 인자로 파일 경로를 받거나, 기본값 사용
file_path = sys.argv[1] if len(sys.argv) > 1 else 'backtest_result_20260112_232300.xlsx'
try:
    df = pd.read_excel(file_path)
    
    # 컬럼 확인 (date가 인덱스로 안 잡혔을 수 있음)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
    print("=== 백테스트 상세 분석 리포트 ===")
    
    # 1. 기본 성과
    start_val = df['total_value'].iloc[0]
    end_val = df['total_value'].iloc[-1]
    total_return = (end_val / start_val) - 1
    
    days = (df.index[-1] - df.index[0]).days
    years = days / 365.25
    cagr = (end_val / start_val) ** (1 / years) - 1
    
    # MDD
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
    
    # 2. 연도별 수익률
    print(f"\n2. 연도별 수익률")
    df['year'] = df.index.year
    yearly_returns = df.groupby('year')['total_value'].apply(lambda x: (x.iloc[-1] / x.iloc[0]) - 1)
    
    for year, ret in yearly_returns.items():
        print(f"   - {year}년: {ret*100:.2f}%")
        
    # 3. 월별 통계
    df['monthly_ret'] = df['total_value'].pct_change()
    best_month = df['monthly_ret'].max()
    worst_month = df['monthly_ret'].min()
    win_rate = (df['monthly_ret'] > 0).mean()
    
    print(f"\n3. 월별 통계")
    print(f"   - 최고 월 수익률: {best_month*100:.2f}%")
    print(f"   - 최악 월 수익률: {worst_month*100:.2f}%")
    print(f"   - 승률 (월간 상승 확률): {win_rate*100:.2f}%")
    
    # 4. 현금 비중 분석 (버그 수정 확인용)
    avg_cash_ratio = (df['cash'] / df['total_value']).mean()
    max_cash_ratio = (df['cash'] / df['total_value']).max()
    
    print(f"\n4. 포트폴리오 구성")
    print(f"   - 평균 현금 비중: {avg_cash_ratio*100:.2f}%")
    print(f"   - 최대 현금 비중: {max_cash_ratio*100:.2f}%")
    
except Exception as e:
    print(f"Error analyzing file: {e}")
