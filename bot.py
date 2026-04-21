import os
import sys
import traceback
import time
import yfinance as yf
import requests
from google import genai
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
# 3. AI分析生成 (Gemini 2.5 Flash)
# ==========================================
def generate_analysis(market_data_str, force_mode=None):
    api_keys = [GEMINI_API_KEY, GEMINI_API_KEY_2]
    valid_keys = [k for k in api_keys if k]
    random.shuffle(valid_keys)

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    calendar_instruction = f"""
【経済指標・イベント】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標（例：米CPI、雇用統計、FOMC、日銀会合等）を特定してください。
- 該当がある場合、冒頭に「⚠️重要指標アラート」を記載。
- 円安による日銀の為替介入や地政学的リスク、政治家の発言など不確定要素でも注意するべき点と現在進行している問題があれば、要点を簡潔にまとめてください。その事柄で暴騰や暴落が起きていたら具体的に記載してください
"""

    if 5 <= hour < 11:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = """昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。
- 前日のニュースや米国セクターETF(XLK/XLF/XLE)の動きから、日本の「追い風」「逆風」セクターと具体銘柄（コード付）を推論。
- 日米金利差とドル円の動向から、輸出株・内需株への影響を解説。"""
    
    elif 15 <= hour < 20:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = """日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください。
- 今日の日本市場の総括。どのセクターや銘柄に資金が集まったかを解説。
- 欧州市場開始後のGold(XAU/USD),US100でロンドン勢が意識しそうな節目（レジサポ）を推論。
- NY市場開場までに予想されるGold(XAU/USD),US100の短期トレンド分析。"""
    
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = """NY市場開場に向けた、US100とGold(XAU/USD)の短期決戦チャート分析です。日本株の情報は不要。
- NY市場開場に向けてUS100,Gold(XAU/USD)のトレンドや、意識される心理的節目、レジサポを分析。
- デイトレードにおける注意点やシナリオ（押し目買い・戻り売り）をまとめてください。
- 指標発表がある場合のボラティリティ予想と立ち回り。
- 個別決算などで値動きが予想される米国銘柄やセクターの解説。"""

    final_prompt = f"""
あなたは日米の投資家から信頼されるトップストラテジスト、そして現役のトレーダーです。
以下のデータとあなたの深い知識を組み合わせ、非常に具体的かつ実戦的なレポートを作成してください。

【最新市場データ】
{market_data_str}
{calendar_instruction}

【指示詳細】
{prompt_content}

【重要：分析・表示ルール】
- 上昇・追い風と予想する銘柄や指数には「🔥」、下落・逆風と予想するものには「🧊」のマークを必ず名称の横に付けること。
- 日本の代表的な銘柄（アドバンテスト(6857)、東京エレクトロン(8035)、三菱UFJ(8306)、トヨタ(7203)など）を積極的に選び、具体的にコード付きで解説に含めること。

【トーン＆マナー】
- 特殊記号（*や_）は絶対に使わず、プレーンテキストと絵文字のみで出力。
- 箇条書きを使い、結論から簡潔に。
- プロらしい深い洞察を含めること。
"""

    response_text = None
    for key in valid_keys:
        try:
            client = genai.Client(api_key=key)
            # モデルを 2.5 Flash に設定
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=final_prompt
            )
            
            if response and response.text:
                response_text = response.text
                print(f"✅ AI分析生成成功 (Key末尾: {key[-4:]})")
                break
        except Exception as e:
            print(f"⚠️ APIエラー (Key末尾: {key[-4:]}): {e}")
            time.sleep(2)
            continue

    if not response_text:
        raise Exception("全てのAPIキーで分析生成に失敗しました。")

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
        res = requests.post(url, json=payload)
        
        if res.status_code == 200:
            print("✅ 完了")
        else:
            print(f"❌ Telegram送信エラー: {res.text}")
            
    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
