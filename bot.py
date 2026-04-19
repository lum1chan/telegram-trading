import os
import sys
import traceback
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
    "Gold": "GC=F",
    "SOX": "^SOX",
    "VIX": "^VIX",
    "US10Y": "^TNX",
    "USD/JPY": "JPY=X",
    "Nikkei225": "^N225",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AAPL": "AAPL",
    "Tech(XLK)": "XLK",
    "Financial(XLF)": "XLF",
    "Energy(XLE)": "XLE"
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

def generate_analysis(market_data_str):
    genai.configure(api_key=GEMINI_API_KEY)
    
    print("--- 利用可能なモデルリストを確認中 ---")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"利用可能モデル: {m.name}")
    except Exception as e:
        print(f"モデルリストの取得に失敗しました: {e}")
    print("---------------------------------------")

    model = genai.GenerativeModel('models/gemini-2.5-flash')
    
    prompt = f"""
あなたはプロのチーフアナリストです。
以下の最新のグローバル市場データを基に、論理的で簡潔かつ、次のアクションに繋がるレポートを作成してください。

【最新市場データ】
{market_data_str}

【レポートの構成と優先順位（厳守）】
1. 【最優先】US100 & XAU/USD 戦略
2. 【重要】海外市場から見た日本株・動意セクター予測
3. 為替（USD/JPY）概況

【トーン＆マナー】
- 結論から述べ、箇条書きを活用すること。
"""
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    # ↓ここが1行になっていることを確認してください
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"【エラー】Telegram送信失敗: {response.text}")
        raise Exception("Telegram API error")

def main():
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")
    print(f"[{now}] 処理を開始します...")

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        
        print("2. AIによる分析を生成中...")
        analysis_report = generate_analysis(market_data)

        print("3. Telegramへ送信中...")
        final_message = f"📊 *Market Briefing - {now}*\n\n{analysis_report}"
        send_telegram_message(final_message)
        print("すべての処理が正常に完了しました！")

    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
