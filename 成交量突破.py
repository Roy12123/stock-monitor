import requests
import pandas as pd
import time
from datetime import datetime, timedelta

def get_5day_avg_volume(tickers, token):
    """取得每支股票的5日平均成交量"""
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {token}"}

    # 計算日期範圍（取最近7個交易日的資料，確保有足夠的資料計算5日均量）
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    volume_5ma_dict = {}

    for ticker in tickers:
        try:
            parameter = {
                "dataset": "TaiwanStockPriceAdj",
                "data_id": ticker,
                "start_date": start_date,
                "end_date": end_date,
            }
            resp = requests.get(url, headers=headers, params=parameter)
            data = resp.json()
            df = pd.DataFrame(data["data"])

            if len(df) >= 5:
                # 計算最近5日的平均成交量
                recent_5_volumes = df.tail(5)['Trading_Volume'].astype(float)
                volume_5ma = recent_5_volumes.mean()/1000
                volume_5ma_dict[ticker] = volume_5ma
            else:
                volume_5ma_dict[ticker] = 0
                print(f"警告: {ticker} 資料不足5日")
        except Exception as e:
            print(f"取得 {ticker} 歷史資料錯誤:", e)
            volume_5ma_dict[ticker] = 0

    return volume_5ma_dict

def vol_detect(tickers, clock, temp_data, volume_5ma_dict):
    token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNS0wNi0yOCAxMDowNzozOSIsInVzZXJfaWQiOiJyb3kxMjEyMyIsImlwIjoiMTA2LjEwNy4xODQuMjAwIn0.SWnXjx27wbWjZ8prDpKcv7wDq2QXocNd3h6R43i0f0U"
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"

    # 記錄每支股票「前一分鐘」的總量
    previous_minute_volume = {}
    last_minute = None  # 記錄上一次更新的分鐘數

    # 不斷執行直到設定時間
    while True:
        now = datetime.now()
        current_minute = now.minute
        print(now)
        if now.hour >= clock:
            print(f"已到{clock}點，結束程式。")
            break

        # 呼叫 API
        parameter = {
            "data_id": tickers,
        }
        try:
            resp = requests.get(url, headers=headers, params=parameter)
            data = resp.json()
            data = pd.DataFrame(data["data"])
        except Exception as e:
            print("API錯誤:", e)
            time.sleep(1)
            continue

        for ticker in tickers:
            data_aa = data[data['stock_id'] == ticker]
            vol = data_aa['total_volume'].iloc[0]
            pct_change = data_aa['change_rate'].iloc[0]
            price = data_aa['buy_price'].iloc[0]

            # 取得該股票的5日均量
            volume_5ma = volume_5ma_dict.get(ticker, 0)

            comp_name = temp_data[temp_data['股票代碼'] == ticker]
            comp_name = comp_name['公司名稱'].iloc[0]

            # 計算前一分鐘的量增加
            if ticker in previous_minute_volume:
                vol_diff = vol - previous_minute_volume[ticker]
            else:
                vol_diff = 0  # 第一次查詢時無法計算差距

            # 判斷：當前成交量 >= 5日均量的20%
            if volume_5ma > 0:
                vol_ratio = vol / volume_5ma
                # print(f'{ticker}, vol: {vol}, vol_ratio: {vol_ratio}')
                if vol_ratio >= 0.20 and pct_change < 11 and price < 250:
                    print(f"{ticker} {comp_name:<8} 此時量為5MA {vol_ratio*100:>6.1f}% , 漲幅: {pct_change:>6.2f} , 價格 {price:>8.2f} , 前一分鐘增量: {vol_diff:>6.0f}張")

        # 當分鐘數改變時，更新前一分鐘的記錄
        if last_minute is None or current_minute != last_minute:
            for ticker in tickers:
                data_aa = data[data['stock_id'] == ticker]
                vol = data_aa['total_volume'].iloc[0]
                previous_minute_volume[ticker] = vol
            last_minute = current_minute

        time.sleep(10)  # 每10秒查詢一次
        print('')
    return

clock = 24
token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNS0wNi0yOCAxMDowNzozOSIsInVzZXJfaWQiOiJyb3kxMjEyMyIsImlwIjoiMTA2LjEwNy4xODQuMjAwIn0.SWnXjx27wbWjZ8prDpKcv7wDq2QXocNd3h6R43i0f0U"

# 讀取監控股票清單
f = '/Users/roysmacbook/Downloads/20251107追蹤.xlsx'
df = pd.read_excel(f)
tickers = df.iloc[:, 0].astype(str).tolist()
tickers = [ticker.replace('.0', '') for ticker in df.iloc[:, 0].astype(str)]

# tickers = tickers + ['6271', '2515']
# tickers = [ '8111', '1815', '8086', '3006']

# 取得公司資訊
url = "https://api.finmindtrade.com/api/v4/data"
headers = {"Authorization": f"Bearer {token}"}
parameter = {
    "dataset": "TaiwanStockInfoWithWarrant",
}
resp = requests.get(url, headers=headers, params=parameter)
comp = resp.json()
comp = pd.DataFrame(comp["data"])
temp_data = comp.iloc[:, [0, 1, 2]].drop_duplicates(subset=[comp.columns[1]]).copy()
temp_data.columns = ['公司產業', '股票代碼', '公司名稱']

# 計算每支股票的5日平均成交量
print("正在計算5日平均成交量...")
volume_5ma_dict = get_5day_avg_volume(tickers, token)
print(f"完成！共計算 {len(volume_5ma_dict)} 支股票的5日均量")
print("")

# 開始監控
vol_detect(tickers, clock, temp_data, volume_5ma_dict)



