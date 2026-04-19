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
    print(f"TELEGRAM_BOT_TOKEN: {'設定あり' if TELEGRAM_BOT_TOKEN else '設定なし（カラ）'}")
    print(f"TELEGRAM_CHAT_ID: {'設定あり' if TELEGRAM_CHAT_ID else '設定なし（カラ）'}")
    print(f"GEMINI_API_KEY: {'設定あり' if GEMINI_API_KEY else '設定なし（カラ）'}")
    print("GitHubの Settings > Secrets and variables > Actions で正しく登録されているか確認してください。")
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
    data_lines =[]
    for name, symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                latest_close = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2]
                pct_change = ((latest_close - prev_close) / prev_close) * 100
                if symbol in["^TNX", "^VIX"]:
                    data_lines.append(f"- {name}: {latest_close:.2f} (前日比 {latest_close - prev_close:+.2f} bp/pt)")
                else:
                    data_lines.append(f"- {name}: {latest_close:.2f} (前日比 {pct_change:+.2f}%)")
        except Exception as e:
            print(f"[警告] {name} のデータ取得に失敗しました: {e}")
            continue
    return "\n".join(data_lines)

def generate_analysis(market_data_str):
    genai.configure(api_key=GEMINI_API_KEY)
    
    # ===== ここを gemini-3.1-pro に変更 =====
    model = genai.GenerativeModel('gemini-3.1-pro')
    # ========================================
    
    prompt = f"""
あなたはプロの機関投資家であり、デイトレーダーに朝のブリーフィングを提供するチーフアナリストです。
以下の最新のグローバル市場データを基に、論理的で簡潔かつ、次のアクション（具体的なトレード戦略）に繋がるレポートを作成してください。

【最新市場データ】
{market_data_str}

【レポートの構成と優先順位（厳守）】
1. 【最優先】US100 & XAU/USD 戦略
   - テクニカル（レジサポ・トレンド）とファンダ（金利(^TNX)・恐怖指数(^VIX)など）を組み合わせて深く分析。
   - 今日の想定レンジやエントリー/エグジットの目線。
   
2. 【重要】海外市場から見た日本株・動意セクター予測
   - SOX指数の動きを基にした、日本の半導体関連（東エレク(8035)、アドバンテスト(6857)等）への波及予測。
   - 米国セクター別騰落（XLK, XLF, XLE）と日本市場の類似セクターへの資金流入・流出連動予測。
   - 米国主要銘柄（NVDA, TSLA, AAPL等）の動きから、日本のサプライヤーや競合銘柄への具体的な影響考察。

3. 為替（USD/JPY）概況
   - 金利差や現在のトレンドを踏まえた要点整理。

【トーン＆マナー】
- 無駄な挨拶は省き、結論から述べること。
- 「〜と思われます」ではなく「〜を想定」「〜に注目」と言い切るプロのトーン。
- スマホ（Telegram）で読みやすいように、適度に改行し、箇条書きを活用すること。文字数は1500字〜2000字程度に収めること。
"""
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"【エラー】Telegram送信失敗: HTTPステータス {response.status_code}")
        print(f"エラー詳細: {response.text}")
        raise Exception("Telegram API error")

# ==========================================
# 3. メイン処理（エラーをキャッチする仕組み）
# ==========================================
def main():
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")
    print(f"[{now}] 処理を開始します...")

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        print("市場データの取得完了:\n", market_data)

        print("2. AIによる分析を生成中... (数秒〜数十秒かかります)")
        analysis_report = generate_analysis(market_data)
        print("AI分析の生成完了！")

        print("3. Telegramへ送信中...")
        final_message = f"📊 *Market Briefing - {now}*\n\n{analysis_report}"
        send_telegram_message(final_message)
        print("すべての処理が正常に完了しました！")

    except Exception as e:
        print("\n=============================================")
        print("❌ 致命的なエラーが発生し、処理が停止しました。")
        print("=============================================")
        print(f"エラーメッセージ: {e}")
        print("\n【詳細なエラーログ】")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
