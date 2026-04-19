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
あなたはプロの投資戦略家です。
以下の最新のグローバル市場データを基に、論理的で簡潔かつ、次のアクションに繋がるレポートを作成してください。

【最新市場データ】
{market_data_str}

【分析の重要ルール】
- 上昇・追い風と予想する銘柄には「🔥」、下落・逆風と予想する銘柄には「🧊」のマークを必ず名称の横に付けてください。
- 上記のデータリストに載っていない銘柄でも、日本の代表的な銘柄（例：アドバンテスト(6857)、東京エレクトロン(8035)、三菱UFJ(8306)、トヨタ(7203)など）を君の知識から積極的に選び、具体的にコード付きで解説に含めること。
- 米国のセクターETF（XLK/XLF/XLE）の騰落から、日本市場のどの業種に資金が流れるかを推論すること。

【レポートの構成と優先順位（厳守）】
1. 【最優先】US100 & XAU/USD デイトレード戦略
2. 【重要】米国市場の総括と日本への影響
   - ナスダックやNVDAの動きから、日本の株式市場の推移を予測。
3. 【追い風】セクター ＆ 具体銘柄
   - 米国で好調だったセクターや指数の動きに基づき、今日日本市場で買われそうな「業種」と「具体的な銘柄（コード付き）」を君の知識から数個挙げてください。
4. 【逆風】セクター ＆ 具体銘柄
   - 金利上昇や米国指数の下落に基づき、今日売り込まれそうな「業種」と「具体的な銘柄（コード付き）」を挙げてください。

【トーン＆マナー】
- 結論から述べ、箇条書きを活用すること。
"""
    response = model.generate_content(prompt)
    return response.text

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

    try:
        print("1. 市場データを取得中...")
        market_data = get_market_data()
        
        print("2. AIによる分析を生成中...")
        analysis_report = generate_analysis(market_data)

        print("3. Telegramへ送信中...")
        # 箇条書きなどの装飾（*）を消したシンプルな形式にする
        final_message = f"=== Market Briefing ===\n日時: {now}\n\n{analysis_report}"
        send_telegram_message(final_message)

    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
