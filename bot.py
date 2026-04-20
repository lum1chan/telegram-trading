import os
import sys
import traceback
import time
import yfinance as yf
import requests
import google.generativeai as genai
from datetime import datetime
import pytz
import random  # 追加：APIキーのシャッフル用

# ==========================================
# 1. 環境変数のチェック
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 2つ目のキーも取得（設定されていなくても動くようにします）
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
    "Gold": "GC=F",           # 【追加】ゴールド（XAU/USD相当）
    "US10Y": "^TNX",          # 米10年債利回り（金利）
    "VIX": "^VIX",            # 恐怖指数
    "USD/JPY": "JPY=X",       # ドル円
    
    # セクターETF（AIに日本のセクターを推論させるための材料）
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

# --- 該当箇所：API分散ロジックを組み込み ---
def generate_analysis(market_data_str, force_mode=None):
    # 利用可能なAPIキーをリスト化してシャッフル
    api_keys = [GEMINI_API_KEY, GEMINI_API_KEY_2]
    valid_keys = [k for k in api_keys if k]
    random.shuffle(valid_keys)

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    # 指示内容の作成（ここは変更なし）
    calendar_instruction = f"""
【最優先指示：経済指標・イベントチェック】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標（例：米CPI、雇用統計、FOMC、日銀会合、ECB理事会等）を特定してください。
- 該当がある場合、レポートの冒頭に「⚠️重要指標アラート」として、日本時間での発表時刻と市場への想定インパクトを記載してください。
- 円安による日銀の為替介入や地政学的リスクなど不確定でも注意するべき点があれば、要点を簡潔にまとめてください。
"""
    if 5 <= hour < 10:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = f"昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください..."
    elif 15 <= hour < 19:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = f"日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください..."
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = f"NY市場開場に向けた、US100とGold(XAU/USD)の短期決戦チャート分析です..."

    final_prompt = f"あなたは日米の投資家から信頼されるトップストラテジスト...（中略）\n{market_data_str}\n{calendar_instruction}\n{prompt_content}"

    # --- APIキーを順番に試すループ ---
    response_text = None
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('models/gemini-2.5-flash')
            response = model.generate_content(final_prompt)
            response_text = response.text
            if response_text:
                print(f"✅ API実行成功 (Key末尾: {key[-4:]})")
                break
        except Exception as e:
            if "429" in str(e):
                print(f"⚠️ API制限(429)発生。次のキーを試します...")
                continue
            else:
                raise e

    if not response_text:
        raise Exception("利用可能なすべてのAPIキーで制限がかかりました。")

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
