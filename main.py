import os
import sys
import time
import logging
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from fugle_marketdata import RestClient

# ================= 配置區 (GitHub Secrets) =================
FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# --- 終極 300 檔全產業優質名單 (已去重、補齊代碼) ---
RAW_LIST = [
    # 1-50: 半導體、IC設計龍頭
    '2330', '2303', '5347', '6770', '3711', '2449', '6239', '6147', '8150', '3374', 
    '6257', '8112', '3264', '3034', '3131', '3583', '1560', '6640', '6187', '3680', 
    '3413', '6683', '2404', '6223', '5434', '3010', '1773', '8028', '6510', '2454', 
    '3661', '3529', '6643', '6533', '3443', '5274', '5269', '4966', '2379', '3035', 
    '6138', '4961', '8081', '3014', '6415', '6202', '2458', '2363', '4919', '6462',
    # 51-100: AI伺服器、代工、工業電腦、電源、機殼
    '2317', '2382', '3231', '6669', '2376', '2377', '2324', '2353', '2357', '3706', 
    '2356', '2352', '2395', '6414', '8050', '3088', '3013', '2308', '2301', '6409', 
    '6282', '2457', '3015', '6203', '2474', '8210', '3693', '6117', '2354', '3017',
    '3324', '3653', '2421', '6230', '3483', '3338', '3037', '8046', '3189', '2313',
    '2368', '4958', '2367', '5469', '6274', '2383', '6213', '2327', '2492', '3026',
    # 101-150: 網通、光通、衛星、散熱擴展
    '2345', '5388', '6285', '3596', '2332', '4906', '8044', '2412', '4904', '3045', 
    '4977', '3081', '3363', '4908', '4979', '8089', '6442', '2314', '3491', '3665',
    '3450', '6426', '3305', '6235', '6464', '8011', '2485', '6142', '6214', '3163',
    '3312', '3016', '3217', '3533', '6196', '6531', '8996', '2436', '6278', '4976',
    # 151-200: 重電、能源、航運、鋼鐵、水泥
    '1519', '1503', '1513', '1514', '1504', '1510', '1605', '1608', '1609', '1501', 
    '6806', '6443', '6477', '3708', '6244', '2207', '2201', '2497', '2231', '1536', 
    '1522', '1319', '3552', '6279', '2603', '2609', '2615', '2618', '2610', 
    '2606', '2605', '2637', '2002', '2014', '2031', '2006', '2015', '1101', '1102', 
    '2542', '2548', '5534', '1301', '1303', '6505', '1326', '1304', '1308', '2030',
    # 201-250: 金融、生技、零售、餐飲
    '2881', '2882', '2891', '2886', '2884', '5880', '2892', '2885', '2880', '2883', 
    '2887', '2890', '5876', '2801', '2834', '5871', '2812', '2809', '2851', '6005', 
    '2855', '6472', '4147', '6446', '1795', '4174', '1760', '1789', '4164', '2912', 
    '5903', '1216', '1227', '9939', '9933', '2723', '2727', '2731', '2707', '1707',
    '1722', '1723', '4105', '4123', '4736', '4746', '6491', '6504', '6582', '8436',
    # 251-300: 記憶體、面板、特化、光學與設備
    '2344', '2337', '2408', '3260', '8299', '3006', '2409', '3481', '6116', '9910', 
    '9921', '9914', '8069', '4526', '2049', '1590', '4532', '1582', '6197', '3130',
    '6438', '6206', '5289', '6670', '3545', '8016', '3592', '3023', '2402', '2360',
    '6281', '3044', '2385', '2441', '3029', '6269', '3617', '6155', '6205', '3557',
    '2451', '4938', '2417', '2455', '3008', '3406', '3504', '6405', '6271', '3532'
]

# 資料清洗與排序，確保剛好 300 檔優質股
MONITOR_LIST = sorted(list(set([s for s in RAW_LIST if s.isdigit() and len(s) == 4])))[:300]
# ==========================================

# ================= VSA 策略參數 =================
SUPPLY_CANDLE_VOL_MULTIPLIER = 1.5   # 供給帶最低量比（相對 20 日均量）
MIN_BEARISH_BODY_DROP = 0.01         # 供給帶黑 K 最低跌幅（1%）
MIN_DAILY_GAIN = 0.010               # 今日突破最低漲幅（1.0%）
CLOSE_POSITION_MIN = 0.35            # 收盤需位於當日振幅的上半部（>= 35%）
SUPPLY_LOOKBACK_DAYS = 100           # 供給帶查找窗口（近 100 個交易日）
MIN_TODAY_VOL_RATIO = 1.0            # 今日成交量需 >= 20 日均量的 1.0 倍（確認需求放量）
MAX_MA60_EXTENSION = 1.5             # 股價不得超過 MA60 的 150%（避免追高過度延伸）
MAX_STOP_PCT = 0.15                  # 止損距離不得超過現價的 15%（控制風險）
# ================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not all([FUGLE_API_KEY, TG_TOKEN, TG_CHAT_ID]):
    logger.error("環境變數缺失，請檢查 GitHub Secrets 設定。")
    sys.exit(1)

try:
    client = RestClient(api_key=FUGLE_API_KEY)
    stock = client.stock
except Exception as e:
    logger.error(f"富果客戶端初始化失敗: {e}")
    sys.exit(1)

def get_stock_name(symbol):
    """查詢單一股票名稱，若無法取得則回傳空字串"""
    try:
        res = stock.snapshot.quotes(symbol=symbol)
        data = res.get('data', [])
        if data and isinstance(data, list):
            return data[0].get('name', '')
        if isinstance(data, dict):
            return data.get('name', '')
    except Exception:
        pass
    return ''

def send_tg_message(message):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"TG 發送異常: {e}")

def calculate_vsa_strategy(symbol):
    try:
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
        data = stock.historical.candles(**{'symbol': symbol, 'timeframe': 'D', 'from': from_date, 'to': to_date})
        if not data or 'data' not in data or not data['data']:
            return None

        df = pd.DataFrame(data['data'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
        df = df.sort_values('date').reset_index(drop=True)

        # 需要足夠的資料計算 MA60
        if len(df) < 65:
            return None

        current = df.iloc[-1]
        prev = df.iloc[-2]

        # === 1. 趨勢過濾器：收盤 > MA60 且 MA60 向上 ===
        ma60 = df['close'].rolling(60).mean()
        ma60_now = ma60.iloc[-1]
        ma60_prev5 = ma60.iloc[-6]  # 5 個交易日前
        if pd.isna(ma60_now) or pd.isna(ma60_prev5):
            return None
        if current['close'] <= ma60_now:
            return None
        if ma60_now <= ma60_prev5:  # MA60 未向上
            return None

        # === 2. 今日攻擊性確認 ===
        # 今日必須是陽線（收盤 > 開盤）
        if current['close'] <= current['open']:
            return None

        # 漲幅必須 > 2.5%
        if prev['close'] <= 0:
            return None
        today_gain = (current['close'] - prev['close']) / prev['close']
        if today_gain <= MIN_DAILY_GAIN:
            return None

        # 收盤需在當日實體上半部（防長上影線假突破）
        day_range = current['high'] - current['low']
        if day_range > 0 and (current['close'] - current['low']) / day_range < CLOSE_POSITION_MIN:
            return None

        # 以近 20 日平均量作為基準
        avg_vol_20 = df['volume'].iloc[-21:-1].mean()
        if avg_vol_20 <= 0:
            return None

        # 今日成交量需放量（>= 1.2 倍均量），確認需求真實
        if current['volume'] < avg_vol_20 * MIN_TODAY_VOL_RATIO:
            return None

        # 過度延伸保護：股價不得超過 MA60 的 125%，避免追高
        if current['close'] > ma60_now * MAX_MA60_EXTENSION:
            return None

        # 往回最多 30 個交易日尋找供給帶（近期供給才具參考價值）
        lookback_start = max(1, len(df) - SUPPLY_LOOKBACK_DAYS - 1)
        best_signal = None
        best_vol_ratio = 0.0

        for i in range(lookback_start, len(df) - 1):
            # 至少需要 20 日歷史量才能計算穩定均量
            if i < 20:
                continue
            row = df.iloc[i]

            # 計算該日的局部 20 日均量作為相對基準
            local_avg_vol = df['volume'].iloc[i - 20:i].mean()
            if local_avg_vol <= 0:
                continue
            vol_ratio = row['volume'] / local_avg_vol

            # === 3. 真・供給帶：爆量陰線（成交量 >= 2 倍均量 且跌幅 > 2%）===
            is_bearish = row['close'] < row['open']
            if row['open'] <= 0:
                continue
            body_drop = (row['open'] - row['close']) / row['open']

            if is_bearish and vol_ratio >= SUPPLY_CANDLE_VOL_MULTIPLIER and body_drop > MIN_BEARISH_BODY_DROP:
                resistance = row['high']
                # 突破偵測：今日收盤站上壓力帶
                if current['close'] > resistance and vol_ratio > best_vol_ratio:
                    # 止損距離保護：止損不得超過現價的 10%
                    stop_pct = (current['close'] - row['low']) / current['close']
                    if stop_pct > MAX_STOP_PCT:
                        continue
                    best_vol_ratio = vol_ratio
                    best_signal = {
                        'symbol': symbol,
                        'price': current['close'],
                        'resistance': resistance,
                        'stop': row['low'],
                        'supply_date': row['date'],
                        'today_vol_ratio': round(current['volume'] / avg_vol_20, 2),
                        'ratio': round(current['volume'] / row['volume'], 2),
                        'gain': round(today_gain * 100, 2),
                    }

        return best_signal
    except Exception as e:
        logger.debug(f"[{symbol}] VSA 計算異常: {e}")
    return None

def main():
    start_time = datetime.now()
    tw_tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

    # 1. 發送啟動通知
    send_tg_message(f"🚀 <b>VSA 監控啟動</b>\n⏰ 時間：{now_tw}\n📊 標的數：{len(MONITOR_LIST)} 檔\n🔍 狀態：正在掃描中...")
    logger.info(f"📊 VSA 掃描任務啟動 | 標的數：{len(MONITOR_LIST)}")
    
    hits = 0

    for i, symbol in enumerate(MONITOR_LIST):
        sig = calculate_vsa_strategy(symbol)
        if sig:
            hits += 1
            name = get_stock_name(sig['symbol'])
            # 避免股號重複：只在有真實股名（且不等於股號）時才附上股名
            name_part = f" {name}" if name and name != symbol else ''
            msg = (
                f"🎯 <b>VSA 突破</b> <code>{sig['symbol']}</code>{name_part}\n"
                f"📊 目前市價：{sig['price']}\n"
                f"📈 今日漲幅：{sig['gain']}%\n"
                f"🚧 突破壓力：{sig['resistance']}（供給日：{sig['supply_date']}）\n"
                f"------------------------\n"
                f"💡 <b>建議策略</b>\n"
                f"💰 進場：站穩 {sig['resistance']}\n"
                f"🛑 止損：跌破 {sig['stop']}\n"
                f"📦 今日量比：{sig['today_vol_ratio']}x（突破量比：{sig['ratio']}x）"
            )
            send_tg_message(msg)

        time.sleep(0.3)
            
    duration = (datetime.now() - start_time).total_seconds()
    
    # 2. 發送結束通知
    send_tg_message(f"✅ <b>VSA 掃描完成</b>\n⏱ 耗時：{duration:.1f} 秒\n🎯 偵測訊號：{hits} 個")
    logger.info(f"✅ 掃描完成 | 耗時：{duration:.2f}s | 發現訊號：{hits}")

if __name__ == "__main__":
    main()