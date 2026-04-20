import os
import sys
import traceback
import time
import yfinance as yf
import requests
import google.generativeai as genai
from datetime import datetime
import pytz

# ==========================================
# 1. 環境変数のチェック
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not GEMINI_API_KEY:
    print("【エラー】環境変数が設定されていません！")
    sys.exit(1)

# ==========================================
# 2. 各種処理
# ==========================================
TICKERS = {
    "US100": "^NDX",
    "SOX": "^SOX",
    "NVDA": "NVDA",
    "Gold": "GC=F",
    "US10Y": "^TNX",
    "VIX": "^VIX",
    "USD/JPY": "JPY=X",
    "Tech(XLK)": "XLK",
    "Financial(XLF)": "XLF",
    "Energy(XLE)": "XLE",
    "Nikkei225": "^N225"
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
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemini-2.0-flash')
    
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    calendar_instruction = f"""
【最優先指示：経済指標・イベントチェック】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標を特定してください。
- 該当がある場合、冒頭に「⚠️重要指標アラート」を記載してください。
"""

    if 5 <= hour < 10:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = "昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。"
    elif 15 <= hour < 19:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = "日本市場の引け整理と、ロンドン市場の動向、GoldやUS100の節目を推論してください。"
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = "NY市場開場に向けたUS100とGoldの短期分析をしてください。日本株の情報は不要です。"

    analysis_rules = """
- 上昇・追い風には「🔥」、下落・逆風には「🧊」を付ける。
- 代表的な日本銘柄(6857, 8035, 8306, 7203等)を具体的に含める。
"""    

    final_prompt = f"""
あなたは凄腕ストラテジストです。
【最新市場データ】
{market_data_str}
{calendar_instruction}
【指示詳細】
{prompt_content}
{analysis_rules}
- 特殊記号（*や_）は使わず、プレーンテキストと絵文字のみで出力してください。
"""

    response = model.generate_content(final_prompt)
    return f"{mode_title}\n\n{response.text}"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"【エラー】Telegram送信失敗: {response.text}")

def main():
    jst = pytz.timezone('Asia/Tokyo')
    now_dt = datetime.now(jst)
    # ここで now_str を定義して、エラーを解消します
    now_str = now_dt.strftime("%Y/%m/%d %H:%M JST")
    print(f"[{now_str}] 処理を開始します...")

    event_name = os.getenv("GITHUB_EVENT_NAME")

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        
        if event_name == "workflow_dispatch":
            print("💡 手動実行：3パターン生成します。")
            for h in [7, 17, 21]:
                analysis_report = generate_analysis(market_data, force_mode=h)
                final_message = f"=== Market Briefing ===\n設定時刻: {h}:00想定\n\n{analysis_report}"
                send_telegram_message(final_message)
                time.sleep(3)
        else:
            print("2. AIによる分析を生成中...")
            analysis_report = generate_analysis(market_data)
            print("3. Telegramへ送信中...")
            # 定義した now_str を使用
            final_message = f"=== Market Briefing ===\n日時: {now_str}\n\n{analysis_report}"
            send_telegram_message(final_message)

    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
