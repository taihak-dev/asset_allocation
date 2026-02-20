import sqlite3
import pandas as pd
import os
from datetime import datetime

DB_PATH = 'market_data.db'

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    """
    DB 테이블 초기화
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # 주가 데이터 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker TEXT,
            date TEXT,
            adjClose REAL,
            close REAL,
            high REAL,
            low REAL,
            open REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        )
    ''')
    
    # FRED 데이터 테이블 (실업률, VIX 등)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fred_data (
            series_id TEXT,
            date TEXT,
            value REAL,
            PRIMARY KEY (series_id, date)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_last_date(ticker):
    """
    해당 티커의 DB상 가장 최근 날짜를 반환 (없으면 None)
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM daily_prices WHERE ticker = ?", (ticker,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def save_prices(ticker, df):
    """
    DataFrame을 DB에 저장 (중복 시 무시 혹은 덮어쓰기)
    """
    if df.empty:
        return

    conn = get_connection()
    
    # DataFrame을 DB 스키마에 맞게 변형
    # df의 인덱스가 date라고 가정
    df_save = df.reset_index()
    
    # date 컬럼을 문자열로 통일
    if 'date' in df_save.columns:
        df_save['date'] = df_save['date'].astype(str)
        
    df_save['ticker'] = ticker
    
    # 필요한 컬럼만 추출 (API 응답에 따라 컬럼명이 다를 수 있으므로 확인)
    cols_to_save = ['ticker', 'date', 'adjClose', 'close', 'high', 'low', 'open', 'volume']
    
    # 없는 컬럼은 NaN 처리 후 0이나 적절한 값으로 채움
    for col in cols_to_save:
        if col not in df_save.columns:
            df_save[col] = None
            
    data_to_insert = df_save[cols_to_save].values.tolist()
    
    cursor = conn.cursor()
    cursor.executemany('''
        INSERT OR REPLACE INTO daily_prices (ticker, date, adjClose, close, high, low, open, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', data_to_insert)
    
    conn.commit()
    conn.close()
    print(f"[DB] Saved {len(df)} rows for {ticker}")

def load_prices(ticker, start_date=None):
    """
    DB에서 데이터 로드
    """
    conn = get_connection()
    query = "SELECT * FROM daily_prices WHERE ticker = ?"
    params = [ticker]
    
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
        
    query += " ORDER BY date ASC"
    
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        # 숫자형 변환
        cols = ['adjClose', 'close', 'high', 'low', 'open', 'volume']
        for col in cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    return df

# --- FRED 관련 ---

def get_last_fred_date(series_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM fred_data WHERE series_id = ?", (series_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def save_fred_data(series_id, df):
    # df index is date, column is value (usually named by series_id)
    if df.empty: return
    
    conn = get_connection()
    df_save = df.reset_index()
    # FRED 데이터는 보통 컬럼명이 series_id와 같거나 'value'임.
    # 첫번째 컬럼을 값으로 간주
    val_col = df_save.columns[1] 
    
    df_save['date'] = df_save['date'].astype(str)
    df_save['series_id'] = series_id
    df_save['value'] = df_save[val_col]
    
    data = df_save[['series_id', 'date', 'value']].values.tolist()
    
    cursor = conn.cursor()
    cursor.executemany('INSERT OR REPLACE INTO fred_data (series_id, date, value) VALUES (?, ?, ?)', data)
    conn.commit()
    conn.close()
    print(f"[DB] Saved FRED data for {series_id}")

def load_fred_data(series_id):
    conn = get_connection()
    df = pd.read_sql("SELECT date, value FROM fred_data WHERE series_id = ? ORDER BY date ASC", conn, params=[series_id])
    conn.close()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
    return df
