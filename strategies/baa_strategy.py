from datetime import datetime, timedelta
from utils.tiingo_utils import get_price_at_date

def get_return_at_date(ticker, days, current_date, df_cache=None):
    """
    특정 기간(days) 수익률 계산
    """
    if isinstance(current_date, str):
        curr_dt = datetime.strptime(current_date, '%Y-%m-%d')
    else:
        curr_dt = current_date
        
    past_dt = curr_dt - timedelta(days=days)
    
    price_now = get_price_at_date(ticker, curr_dt, df_cache)
    price_past = get_price_at_date(ticker, past_dt, df_cache)
    
    if price_now is None or price_past is None or price_past == 0:
        return None
        
    return (price_now / price_past) - 1

def calculate_13612w_score(ticker, current_date, df_cache=None):
    """
    13612W 모멘텀 스코어 계산
    (12 * 1m) + (4 * 3m) + (2 * 6m) + (1 * 12m)
    """
    r1 = get_return_at_date(ticker, 30, current_date, df_cache)
    r3 = get_return_at_date(ticker, 90, current_date, df_cache)
    r6 = get_return_at_date(ticker, 180, current_date, df_cache)
    r12 = get_return_at_date(ticker, 365, current_date, df_cache)
    
    if None in [r1, r3, r6, r12]:
        return None
        
    return (12 * r1) + (4 * r3) + (2 * r6) + (1 * r12)

def get_relative_momentum(ticker, current_date, df_cache=None):
    """
    상대 모멘텀 (보통 최근 1~12개월 수익률 평균 또는 특정 기간 수익률)
    BAA 원전에서는 공격 자산 선택 시 13612W가 아닌 단순 수익률(주로 12개월)을 보기도 하나,
    여기서는 일관성을 위해 13612W 스코어를 그대로 사용하거나 12개월 수익률을 사용.
    연구 결과에 따라 '가장 강한 자산'을 뽑는 기준을 12개월 수익률로 설정.
    """
    return get_return_at_date(ticker, 365, current_date, df_cache)

def baa_g4_strategy(total_asset_value, current_date=None, df_cache=None):
    if current_date is None:
        current_date = datetime.now()
        
    # 1. 유니버스 정의
    # Canary: 시장 감시용
    canary_assets = ['SPY', 'EFA', 'EEM', 'AGG']
    
    # Offensive: 공격용 (레버리지 포함)
    # QLD(나스닥2x), SSO(S&P2x), EFA(선진국), EEM(신흥국)
    # 데이터가 없을 경우를 대비해 백테스트 시에는 대용치 고려 필요하나 여기선 티커 명시
    offensive_assets = ['QLD', 'SSO', 'EFA', 'EEM']
    
    # Defensive: 수비용
    defensive_assets = ['BIL', 'IEF', 'LQD', 'AGG']
    
    all_assets = list(set(canary_assets + offensive_assets + defensive_assets))
    
    # 2. 카나리아 신호 확인 (Risk Check)
    # 4개 중 하나라도 스코어가 <= 0 이면 Risk-Off
    risk_on = True
    for asset in canary_assets:
        score = calculate_13612w_score(asset, current_date, df_cache)
        if score is None:
            # 데이터 부족 시 보수적으로 Risk-Off
            risk_on = False
            break
        if score <= 0:
            risk_on = False
            break
            
    # 3. 자산 선택
    selected_asset = None
    
    if risk_on:
        # 공격 자산 중 모멘텀(12개월 수익률 or 13612W) 1위 선택
        # 여기서는 반응성을 위해 13612W 스코어 기준으로 1위 선정
        best_score = -9999
        for asset in offensive_assets:
            score = calculate_13612w_score(asset, current_date, df_cache)
            if score is not None and score > best_score:
                best_score = score
                selected_asset = asset
    else:
        # 수비 자산 중 모멘텀 1위 선택 (안전 자산)
        # 단, BIL(현금)보다 모멘텀이 낮으면 BIL 선택 (Cash Protection)
        best_score = -9999
        best_defensive = 'BIL'
        
        # BIL 스코어 먼저 계산
        bil_score = calculate_13612w_score('BIL', current_date, df_cache)
        if bil_score is None: bil_score = 0
        
        for asset in defensive_assets:
            if asset == 'BIL': continue
            score = calculate_13612w_score(asset, current_date, df_cache)
            if score is not None and score > best_score:
                best_score = score
                best_defensive = asset
        
        # 현금보다 못한 채권은 사지 않음
        if best_score < bil_score:
            selected_asset = 'BIL'
        else:
            selected_asset = best_defensive

    # 4. 할당 결과 반환
    allocation = {asset: 0.0 for asset in all_assets}
    if selected_asset:
        allocation[selected_asset] = float(total_asset_value)
        
    return allocation
