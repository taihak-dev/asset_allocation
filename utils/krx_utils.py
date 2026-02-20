import FinanceDataReader as fdr
from datetime import datetime, timedelta
import pandas as pd

def get_krx_price(ticker):
    """
    한국 주식(ETF)의 최신 종가를 반환합니다.
    """
    try:
        # 최근 5일치 데이터 조회 (휴장일 대비)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        df = fdr.DataReader(ticker, start_date, end_date)
        
        if df.empty:
            return None
            
        # 가장 최근 종가
        return df['Close'].iloc[-1]
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch KRX price for {ticker}: {e}")
        return None

def get_krx_name(ticker):
    # config에 있는 이름 맵핑 사용 권장
    return ticker
