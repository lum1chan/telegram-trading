import os
import sys
import traceback
import time
import yfinance as yf
import requests
import google.generativeai as genai
from datetime import datetime
import pytz
import random

# ==========================================
# 1. 環境変数のチェック
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not GEMINI_API_KEY:
    print("【エラー】環境変数が設定されていません！")
    sys.exit(1)

# ==========================================
# 2. 各種処理
# ==========================================
TICKERS = {
    "US100": "^NDX",          # ナスダック100
    "SOX": "^SOX",            # 半導体指数
    "NVDA": "NVDA",           # エヌビディア
    "Gold": "GC=F",           # ゴールド
    "US10Y": "^TNX",          # 米10年債利回り
    "VIX": "^VIX",            # 恐怖指数
    "USD/JPY": "JPY=X",       # ドル円
    "Tech(XLK)": "XLK",       # 米国ハイテク
    "Financial(XLF)": "XLF",  # 米国金融
    "Energy(XLE)": "XLE",     # 米国エネルギー
    "Nikkei225": "^N225"      # 日経平均
}

def get_market_data():
    data_lines = []
    for name, symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                latest_close = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2]
                pct_change = ((latest_close - prev_close) / prev_close) * 100
                if symbol in ["^TNX", "^VIX"]:
                    data_lines.append(f"- {name}: {latest_close:.2f} (前日比 {latest_close - prev_close:+.2f} bp/pt)")
                else:
                    data_lines.append(f"- {name}: {latest_close:.2f} (前日比 {pct_change:+.2f}%)")
        except Exception as e:
            print(f"[警告] {name} のデータ取得に失敗しました: {e}")
            continue
    return "\n".join(data_lines)

def generate_analysis(market_data_str, force_mode=None):
    # 利用可能なAPIキーをリスト化してシャッフル
    api_keys = [GEMINI_API_KEY, GEMINI_API_KEY_2]
    valid_keys = [k for k in api_keys if k]
    random.shuffle(valid_keys)

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    calendar_instruction = f"""
【最優先指示：経済指標・イベントチェック】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標（例：米CPI、雇用統計、FOMC、日銀会合、ECB理事会等）を特定してください。
- 該当がある場合、レポートの冒頭に「⚠️重要指標アラート」として、日本時間での発表時刻と市場への想定インパクトを記載してください。
- 円安による日銀の為替介入や地政学的リスクなど不確定でも注意するべき点があれば、要点を簡潔にまとめてください。
"""

    if 5 <= hour < 10:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = f"昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。昨晩のナスダックやSOX指数の動きを日経平均への影響に結びつけてください。"
    elif 15 <= hour < 19:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = f"日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください。夜の米株市場への橋渡しとなる視点をお願いします。"
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = f"NY市場開場に向けた、US100とGold(XAU/USD)の短期決戦チャート分析です。金利(US10Y)の動きを意識した解説をしてください。"

    final_prompt = f"あなたは日米の投資家から信頼されるトップストラテジストです。以下の市場データに基づき、プロの視点で簡潔かつ鋭い分析レポートを作成してください。\n\n【市場データ】\n{market_data_str}\n\n{calendar_instruction}\n\n【分析リクエスト】\n{prompt_content}"

    # --- API実行ループ（安定版モデル + リトライ待機 + 404対策済み） ---
    response_text = None
    for key in valid_keys:
        for attempt in range(2):  # 各キーで最大2回試行
            try:
                genai.configure(api_key=key)
                # モデル名から 'models/' を外して指定（404エラー対策）
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(final_prompt)
                response_text = response.text
                if response_text:
                    print(f"✅ API実行成功 (Key末尾: {key[-4:]})")
                    break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg:
                    wait_time = 30  # IP制限回避のためのクールダウン
                    print(f"⚠️ 制限(429)発生 (Key末尾: {key[-4:]})。{wait_time}秒待機して再試行します({attempt+1}/2)...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ エラー発生: {e}")
                    break
        
        if response_text:
            break

    if not response_text:
        raise Exception("利用可能なすべてのAPIキーで制限またはエラーが発生しました。")

    return f"{mode_title}\n\n{response_text}"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"【エラー】Telegram送信失敗: {response.text}")
        raise Exception("Telegram API error")

def main():
    jst = pytz.timezone('Asia/Tokyo')
    here_now = datetime.now(jst)
    now_str = here_now.strftime("%Y/%m/%d %H:%M JST")
    print(f"[{now_str}] 処理を開始します...")

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        print("2. AIによる分析を生成中...")
        analysis_report = generate_analysis(market_data)
        print("3. Telegramへ送信中...")
        final_message = f"=== Market Briefing ===\n日時: {now_str}\n\n{analysis_report}"
        send_telegram_message(final_message)
        print("✅ 全ての処理が完了しました。")
    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
