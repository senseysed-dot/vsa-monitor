import os
import sys
import time
import logging
import pandas as pd
import requests
import pytz
from datetime import datetime
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
    '1522', '1319', '东阳', '3552', '6279', '2603', '2609', '2615', '2618', '2610', 
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
    try:
        res = stock.snapshot.quotes(symbol=symbol)
        return res.get('data', [{}])[0].get('name', '')
    except: return ''

def send_tg_message(message):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"TG 發送異常: {e}")

def calculate_vsa_strategy(symbol):
    try:
        data = stock.historical.candles(symbol=symbol, timeframe='D')
        if not data or 'data' not in data or not data['data']: return None
        
        df = pd.DataFrame(data['data'])
        if len(df) < 22: return None
        
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        current = df.iloc[-1]
        lookback = df.iloc[-21:-1]
        
        max_vol_idx = lookback['volume'].idxmax()
        max_vol_row = lookback.loc[max_vol_idx]
        
        loc_idx = df.index.get_loc(max_vol_idx)
        if loc_idx == 0: return None
        prev_vol = df.iloc[loc_idx - 1]['volume']
        
        # VSA 核心判定：倍量陰線 (陰線且量 >= 前日2倍)
        if max_vol_row['close'] < max_vol_row['open'] and max_vol_row['volume'] >= (prev_vol * 2):
            resistance = max_vol_row['high']
            # 突破偵測：今日價 > 壓力位 且 今日量 < 歷史高量 (縮量過頂)
            if current['close'] > resistance and current['volume'] < max_vol_row['volume']:
                return {
                    'symbol': symbol,
                    'price': current['close'],
                    'resistance': resistance,
                    'stop': max_vol_row['low'],
                    'ratio': round(current['volume'] / max_vol_row['volume'], 2)
                }
    except: pass
    return None

def main():
    start_time = datetime.now()
    tw_tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

    # 1. 發送啟動通知
    send_tg_message(f"🚀 **VSA 監控啟動**\n⏰ 時間：`{now_tw}`\n📊 標的數：`{len(MONITOR_LIST)}` 檔\n🔍 狀態：正在掃描中...")
    logger.info(f"📊 VSA 掃描任務啟動 | 標的數：{len(MONITOR_LIST)}")
    
    hits = 0
    for i, symbol in enumerate(MONITOR_LIST):
        sig = calculate_vsa_strategy(symbol)
        if sig:
            hits += 1
            name = get_stock_name(symbol)
            msg = (
                f"🎯 **VSA 突破：{sig['symbol']} {name}**\n"
                f"📊 目前市價：`{sig['price']}`\n"
                f"🚧 壓力堡壘：`{sig['resistance']}`\n"
                f"------------------------\n"
                f"💡 **建議策略**\n"
                f"💰 進場：站穩 `{sig['resistance']}`\n"
                f"🛑 止損：跌破 `{sig['stop']}`\n"
                f"📉 突破量比：`{sig['ratio']}`"
            )
            send_tg_message(msg)
            
        if i % 15 == 0:
            time.sleep(0.4)
            
    duration = (datetime.now() - start_time).total_seconds()
    
    # 2. 發送結束通知
    send_tg_message(f"✅ **VSA 掃描完成**\n⏱ 耗時：`{duration:.1f}` 秒\n🎯 偵測訊號：`{hits}` 個")
    logger.info(f"✅ 掃描完成 | 耗時：{duration:.2f}s | 發現訊號：{hits}")

if __name__ == "__main__":
    main()