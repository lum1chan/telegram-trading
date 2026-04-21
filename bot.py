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
# 2. 市場データ取得
# ==========================================
TICKERS = {
    "US100": "^NDX", "SOX": "^SOX", "NVDA": "NVDA", "Gold": "GC=F",
    "US10Y": "^TNX", "VIX": "^VIX", "USD/JPY": "JPY=X",
    "Tech(XLK)": "XLK", "Financial(XLF)": "XLF", "Energy(XLE)": "XLE",
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
        except: continue
    return "\n".join(data_lines)

# ==========================================
# 3. AI分析生成 (Gemini 1.5 Flash 安定版)
# ==========================================
def generate_analysis(market_data_str, force_mode=None):
    api_keys = [GEMINI_API_KEY, GEMINI_API_KEY_2]
    valid_keys = [k for k in api_keys if k]
    random.shuffle(valid_keys)

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    # --- 分析の重要ルール (🔥/🧊 と 日本主力銘柄の指示を追加) ---
    analysis_rules = """
【分析の重要ルール】
- 上昇・追い風と予想する銘柄や指数には「🔥」、下落・逆風と予想するものには「🧊」のマークを必ず名称の横に付けてください。
- リストにない銘柄でも、日本の代表的な銘柄（アドバンテスト(6857)、東京エレクトロン(8035)、三菱UFJ(8306)、トヨタ(7203)など）を君の知識から積極的に選び、具体的にコード付きで解説に含めること。
- 回答はTelegramで配信するため、箇条書きを活用して視認性を高めてください。
"""

    calendar_instruction = f"""
【最優先指示：経済指標・イベントチェック】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標（例：米CPI、雇用統計、FOMC、日銀会合等）を特定してください。
- 該当がある場合、冒頭に「⚠️重要指標アラート」を記載してください。
"""

    # --- 時間帯別プロンプト ---
    if 5 <= hour < 10:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = f"""昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。
- 前日のニュースや米国セクターETF(XLK/XLF/XLE)の動きから、日本の「追い風」「逆風」セクターと具体銘柄（コード付）を推論。
- 日米金利差とドル円の動向から、輸出株・内需株への影響を解説。"""
    
    elif 15 <= hour < 19:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = f"""日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください。
- 今日の日本市場の総括。どのセクターや銘柄に資金が集まったかを解説。
- 欧州市場開始後のGold(XAU/USD),US100でロンドン勢が意識しそうな節目を推論。
- NY市場開場までに予想されるGold(XAU/USD),US100の短期トレンド分析。"""
    
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = f"""NY市場開場に向けた、US100とGold(XAU/USD)の短期決戦チャート分析です。日本株の情報は不要。
- NY市場開場に向けてUS100,Gold(XAU/USD)のトレンドや推移などについて分析してください。
- US100,Gold(XAU/USD)のデイトレードで意識することをまとめてください。
- 指標発表がある場合は、発表直後のボラティリティ予想と立ち回り。
- 前日のニュースなどで値動きが予想される銘柄やセクターをまとめて解説。"""

    final_prompt = f"あなたは日米のトップストラテジストです。\n{analysis_rules}\n\n【市場データ】\n{market_data_str}\n\n{calendar_instruction}\n\n【分析リクエスト】\n{prompt_content}"

    # --- API実行ループ (404対策) ---
    response_text = None
    model_names = ['gemini-1.5-flash', 'models/gemini-1.5-flash']

    for key in valid_keys:
        genai.configure(api_key=key)
        for m_name in model_names:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content(final_prompt)
                if response and response.text:
                    response_text = response.text
                    break
            except: continue
        if response_text: break

    if not response_text:
        raise Exception("分析生成に失敗しました。")

    return f"{mode_title}\n\n{response_text}"

# ==========================================
# 4. メイン処理
# ==========================================
def main():
    jst = pytz.timezone('Asia/Tokyo')
    now_str = datetime.now(jst).strftime("%Y/%m/%d %H:%M")
    
    try:
        market_data = get_market_data()
        analysis = generate_analysis(market_data)
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"=== Briefing ===\n{analysis}"}
        requests.post(url, json=payload)
        print("✅ 完了")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
