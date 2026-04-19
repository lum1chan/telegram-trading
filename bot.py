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

def generate_analysis(market_data_str, force_mode=None): # ← force_modeを追加
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-flash')
    
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    
    # 手動実行で時間が指定された場合はそれを使う。なければ現在時刻。
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    # --- 共通の経済指標・カレンダー指示 ---
    calendar_instruction = f"""
【最優先指示：経済指標・イベントチェック】
- 本日（{today_str}）および直近24時間以内に発表される重要経済指標（例：米CPI、雇用統計、FOMC、日銀会合、ECB理事会等）を特定してください。
- 該当がある場合、レポートの冒頭に「⚠️重要指標アラート」として、日本時間での発表時刻と市場への想定インパクトを記載してください。
- 円安による日銀の為替介入や地政学的リスクなど不確定でも注意すべき要点を簡潔にまとめてください。
"""

    # --- ① 朝モード (AM 5:00 - AM 9:59) ---
    if 5 <= hour < 10:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = f"""
昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。
- 米国セクターETF(XLK/XLF/XLE)の動きから、日本の「追い風(🔥)」「逆風(🧊)」セクターと具体銘柄（コード付）を推論。
- 日米金利差とドル円の動向から、輸出株・内需株への影響を解説。
"""

    # --- ② 夕方モード (PM 15:00 - PM 18:59) ---
    elif 15 <= hour < 19:
        mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
        prompt_content = f"""
日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください。
- 今日の日本市場の総括（なぜ上がったか/下がったか）。
- 欧州市場開始後のGold(XAU/USD)、US100と、ロンドン勢が意識しそうな節目を推論。NY市場開場までに予想される地政学的リスクなども含めた分析をしてください。
"""

    # --- ③ 夜モード (PM 19:00 - AM 4:59) ---
    else:
        mode_title = f"🌃 【夜：NY開場直前・米株/ゴールド特化】{today_str}"
        prompt_content = f"""
NY市場開場に向けた、US100とGold(XAU/USD)の短期決戦チャート分析です。日本株の情報は不要です。
- NY市場開場に向けてUS100,Gold(XAU/USD)のトレンドや推移などについて分析してください。その日意識することも書いてください。
- 指標発表がある場合は、発表直後のボラティリティ予想と立ち回り。
- US10Y（金利）とVIXから、現在の市場の「攻め時・守り時」を判定してください。
"""
    analysis_rules = """
【分析の重要ルール】
- 上昇・追い風と予想する銘柄や指数には「🔥」、下落・逆風と予想するものには「🧊」のマークを必ず名称の横に付けてください。
- リストにない銘柄でも、日本の代表的な銘柄（アドバンテスト(6857)、東京エレクトロン(8035)、三菱UFJ(8306)、トヨタ(7203)など）を君の知識から積極的に選び、具体的にコード付きで解説に含めること。
- 米国のセクターETF（XLK/XLF/XLE）の騰落から、日本市場のどの業種に資金が流れるかを推論すること。
"""    

    # 最終的なプロンプトの組み立て
    final_prompt = f"""
あなたは日米の機関投資家から信頼されるトップストラテジストです。
以下のデータとあなたの知識を組み合わせ、非常に具体的かつ実戦的なレポートを作成してください。

【最新市場データ】
{market_data_str}

{calendar_instruction}

【指示詳細】
{prompt_content}

【トーン＆マナー】
- 特殊記号（*や_）は絶対に使わず、プレーンテキストと絵文字のみで出力。
- 箇条書きを使い、結論から簡潔に。
- プロらしい深い洞察を含めること。
"""

    response = model.generate_content(final_prompt)
    return f"{mode_title}\n\n{response.text}"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        # "parse_mode": "Markdown"  <-- この行を削除、またはコメントアウト
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"【エラー】Telegram送信失敗: {response.text}")
        raise Exception("Telegram API error")

def main():
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")
    print(f"[{now}] 処理を開始します...")

    event_name = os.getenv("GITHUB_EVENT_NAME")

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        
        if event_name == "workflow_dispatch":
            print("💡 手動実行：朝・夕・夜の3パターンを生成します。")
            # 7時(朝)、17時(夕)、21時(夜)の順で送信
            for h in [7, 17, 21]:
                print(f"2-{h}. AI分析生成中 ({h}:00想定)...")
                analysis_report = generate_analysis(market_data, force_mode=h)
                
                final_message = f"=== Market Briefing ===\n設定時刻: {h}:00想定\n\n{analysis_report}"
                send_telegram_message(final_message)
                
                print(f"3-{h}. Telegramへ送信完了")
                time.sleep(3) # 連続送信エラー防止
        else:
            # 通常の自動実行
            print("2. AIによる分析を生成中...")
            analysis_report = generate_analysis(market_data)

            print("3. Telegramへ送信中...")
            final_message = f"=== Market Briefing ===\n日時: {now_str}\n\n{analysis_report}"
            send_telegram_message(final_message)

    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
