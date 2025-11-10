from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'stock_monitor_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全域變數
monitoring_data = []
is_monitoring = False
monitor_thread = None
token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNS0wNi0yOCAxMDowNzozOSIsInVzZXJfaWQiOiJyb3kxMjEyMyIsImlwIjoiMTA2LjEwNy4xODQuMjAwIn0.SWnXjx27wbWjZ8prDpKcv7wDq2QXocNd3h6R43i0f0U"

def get_5day_avg_volume(tickers, token):
    """取得每支股票的5日平均成交量"""
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {token}"}

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
                recent_5_volumes = df.tail(5)['Trading_Volume'].astype(float)
                volume_5ma = recent_5_volumes.mean()/1000
                volume_5ma_dict[ticker] = volume_5ma
            else:
                volume_5ma_dict[ticker] = 0
        except Exception as e:
            print(f"取得 {ticker} 歷史資料錯誤:", e)
            volume_5ma_dict[ticker] = 0

    return volume_5ma_dict

def get_company_info(token):
    """取得公司資訊"""
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {token}"}
    parameter = {"dataset": "TaiwanStockInfoWithWarrant"}
    resp = requests.get(url, headers=headers, params=parameter)
    comp = resp.json()
    comp = pd.DataFrame(comp["data"])
    temp_data = comp.iloc[:, [0, 1, 2]].drop_duplicates(subset=[comp.columns[1]]).copy()
    temp_data.columns = ['公司產業', '股票代碼', '公司名稱']
    return temp_data

def vol_detect_background(tickers, temp_data, volume_5ma_dict, min_price=0, max_price=999999):
    """背景執行的監控函式"""
    global monitoring_data, is_monitoring

    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"

    # 記錄不同時間點的成交量和價格
    previous_minute_volume = {}
    volume_history = {}  # {ticker: [(timestamp, volume), ...]}
    price_history = {}   # {ticker: [(timestamp, price), ...]}
    last_minute = None

    while is_monitoring:
        now = datetime.now()
        current_minute = now.minute

        # 呼叫 API
        parameter = {"data_id": tickers}
        try:
            resp = requests.get(url, headers=headers, params=parameter)
            data = resp.json()
            data = pd.DataFrame(data["data"])
        except Exception as e:
            print("API錯誤:", e)
            time.sleep(1)
            continue

        current_alerts = []

        for ticker in tickers:
            try:
                data_aa = data[data['stock_id'] == ticker]
                if len(data_aa) == 0:
                    continue

                vol = data_aa['total_volume'].iloc[0]
                pct_change = data_aa['change_rate'].iloc[0]
                price = data_aa['buy_price'].iloc[0]

                volume_5ma = volume_5ma_dict.get(ticker, 0)

                comp_name = temp_data[temp_data['股票代碼'] == ticker]
                if len(comp_name) > 0:
                    comp_name = comp_name['公司名稱'].iloc[0]
                else:
                    comp_name = ticker

                # 記錄當前成交量到歷史記錄
                if ticker not in volume_history:
                    volume_history[ticker] = []
                volume_history[ticker].append((now, vol))

                # 記錄當前價格到歷史記錄
                if ticker not in price_history:
                    price_history[ticker] = []
                price_history[ticker].append((now, price))

                # 只保留最近3分鐘的記錄
                volume_history[ticker] = [(t, v) for t, v in volume_history[ticker]
                                          if (now - t).total_seconds() <= 180]
                price_history[ticker] = [(t, p) for t, p in price_history[ticker]
                                         if (now - t).total_seconds() <= 180]

                # 計算30秒、1分鐘、2分鐘的增量百分比
                vol_diff_30sec = 0
                vol_diff_1min = 0
                vol_diff_2min = 0
                price_diff_30sec = 0
                price_diff_1min = 0
                price_diff_2min = 0

                # 30秒增量：找最接近30秒前的記錄
                vol_30sec_ago = None
                for t, v in reversed(volume_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 25 <= time_diff <= 35:  # 允許25-35秒的範圍
                        vol_30sec_ago = v
                        break

                if vol_30sec_ago is not None and vol_30sec_ago > 0:
                    vol_increase_30sec = vol - vol_30sec_ago
                    vol_diff_30sec = (vol_increase_30sec / vol_30sec_ago) * 100

                # 1���鐘增量：找最接近1分鐘前的記錄
                vol_1min_ago = None
                for t, v in reversed(volume_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 55 <= time_diff <= 65:  # 允許55-65秒的範圍
                        vol_1min_ago = v
                        break

                if vol_1min_ago is not None and vol_1min_ago > 0:
                    vol_increase_1min = vol - vol_1min_ago
                    vol_diff_1min = (vol_increase_1min / vol_1min_ago) * 100

                # 2分鐘增量：找最接近2分鐘前的記錄
                vol_2min_ago = None
                for t, v in reversed(volume_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 115 <= time_diff <= 125:  # 允許115-125秒的範圍
                        vol_2min_ago = v
                        break

                if vol_2min_ago is not None and vol_2min_ago > 0:
                    vol_increase_2min = vol - vol_2min_ago
                    vol_diff_2min = (vol_increase_2min / vol_2min_ago) * 100

                # 計算價格變化 - 30秒
                price_30sec_ago = None
                for t, p in reversed(price_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 25 <= time_diff <= 35:
                        price_30sec_ago = p
                        break

                if price_30sec_ago is not None and price_30sec_ago > 0:
                    price_diff_30sec = ((price - price_30sec_ago) / price_30sec_ago) * 100

                # 計算價格變化 - 1分鐘
                price_1min_ago = None
                for t, p in reversed(price_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 55 <= time_diff <= 65:
                        price_1min_ago = p
                        break

                if price_1min_ago is not None and price_1min_ago > 0:
                    price_diff_1min = ((price - price_1min_ago) / price_1min_ago) * 100

                # 計算價格變化 - 2分鐘
                price_2min_ago = None
                for t, p in reversed(price_history[ticker]):
                    time_diff = (now - t).total_seconds()
                    if 115 <= time_diff <= 125:
                        price_2min_ago = p
                        break

                if price_2min_ago is not None and price_2min_ago > 0:
                    price_diff_2min = ((price - price_2min_ago) / price_2min_ago) * 100

                # 判斷條件（加入股價上下限）
                if volume_5ma > 0:
                    vol_ratio = vol / volume_5ma
                    if vol_ratio >= 0.20 and pct_change < 11 and min_price <= price <= max_price:
                        alert_data = {
                            'time': now.strftime("%H:%M:%S"),
                            'ticker': ticker,
                            'name': comp_name,
                            'vol_ratio': round(vol_ratio * 100, 1),
                            'pct_change': round(pct_change, 2),
                            'price': round(price, 2),
                            'vol_diff_30sec': round(vol_diff_30sec, 1),
                            'vol_diff_1min': round(vol_diff_1min, 1),
                            'vol_diff_2min': round(vol_diff_2min, 1),
                            'price_diff_30sec': round(price_diff_30sec, 2),
                            'price_diff_1min': round(price_diff_1min, 2),
                            'price_diff_2min': round(price_diff_2min, 2)
                        }
                        current_alerts.append(alert_data)
            except Exception as e:
                print(f"處理 {ticker} 錯誤: {e}")
                continue

        # 更新全域監控資料
        monitoring_data = current_alerts

        # 透過 WebSocket 推送更新
        socketio.emit('update', {
            'data': current_alerts,
            'time': now.strftime("%Y-%m-%d %H:%M:%S")
        })

        # 當分鐘數改變時，更新前一分鐘的記錄
        if last_minute is None or current_minute != last_minute:
            for ticker in tickers:
                try:
                    data_aa = data[data['stock_id'] == ticker]
                    if len(data_aa) > 0:
                        vol = data_aa['total_volume'].iloc[0]
                        previous_minute_volume[ticker] = vol
                except:
                    continue
            last_minute = current_minute

        time.sleep(5)

@app.route('/')
def index():
    """首頁"""
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_monitoring():
    """啟動監控"""
    global is_monitoring, monitor_thread

    data = request.json
    tickers = data.get('tickers', [])
    min_price = data.get('min_price', 0)
    max_price = data.get('max_price', 999999)

    if not tickers:
        return jsonify({'status': 'error', 'message': '請輸入股票代碼'})

    if is_monitoring:
        return jsonify({'status': 'error', 'message': '監控已在執行中'})

    is_monitoring = True

    # 取得公司資訊
    temp_data = get_company_info(token)

    # 計算5日均量
    socketio.emit('status', {'message': '正在計算5日平均成交量...'})
    volume_5ma_dict = get_5day_avg_volume(tickers, token)

    # 啟動背景監控
    monitor_thread = threading.Thread(
        target=vol_detect_background,
        args=(tickers, temp_data, volume_5ma_dict, min_price, max_price),
        daemon=True
    )
    monitor_thread.start()

    socketio.emit('status', {'message': f'開始監控 {len(tickers)} 支股票'})
    return jsonify({'status': 'success', 'tickers_count': len(tickers)})

@app.route('/api/stop', methods=['POST'])
def stop_monitoring():
    """停止監控"""
    global is_monitoring
    is_monitoring = False
    socketio.emit('status', {'message': '監控已停止'})
    return jsonify({'status': 'success', 'message': '監控已停止'})

@app.route('/api/data')
def get_data():
    """取得當前監控資料"""
    return jsonify({
        'data': monitoring_data,
        'is_monitoring': is_monitoring
    })

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5005))
    debug = os.environ.get('FLASK_ENV') != 'production'
    print(f"股票監控系統啟動於 port {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)