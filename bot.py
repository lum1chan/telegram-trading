import os
import sys
import traceback
import time
import xml.etree.ElementTree as ET
import yfinance as yf
import requests
from google import genai
from datetime import datetime, timedelta
import exchange_calendars as xcals
import pytz
import random

# ==========================================
# 1. 環境変数のチェック
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2")
WEBAPP_URL = os.getenv("WEBAPP_URL") # WebアプリのURL (例: https://your-app.onrender.com/api/telegram/webhook)

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not GEMINI_API_KEY:
    print("【エラー】環境変数が設定されていません！")
    sys.exit(1)

# ==========================================
# 2. ニュースRSS取得
# ==========================================
NEWS_FEEDS = [
    ("NHK経済", "https://www3.nhk.or.jp/rss/news/cat6.xml"),
    ("NHK政治", "https://www3.nhk.or.jp/rss/news/cat4.xml"),
    ("Reuters Japan", "https://feeds.reuters.com/reuters/JPbusinessNews"),
]
NEWS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}
MAX_ITEMS_PER_FEED = 6

def get_news_headlines():
    """NHK・Reuters JapanのRSSから最新ヘッドラインを取得する"""
    all_news = []
    for source_name, url in NEWS_FEEDS:
        try:
            resp = requests.get(url, timeout=10, headers=NEWS_HEADERS)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')[:MAX_ITEMS_PER_FEED]
            for item in items:
                title = item.findtext('title', '').strip()
                link = item.findtext('link', '').strip()
                if not link:
                    link = item.findtext('guid', '').strip()
                if title:
                    entry = f"[{source_name}] {title}"
                    if link:
                        entry += f"\n  {link}"
                    all_news.append(entry)
            print(f"✅ {source_name}: {len(items)}件取得")
        except Exception as e:
            print(f"⚠️ {source_name} ニュース取得エラー: {e}")

    if not all_news:
        return None
    return "\n".join(all_news)

# ==========================================
# 3. 経済カレンダー取得 (ForexFactory XML)
# ==========================================
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
CALENDAR_COUNTRIES = {"USD", "JPY"}
CALENDAR_IMPACTS = {"High", "Medium"}

def get_economic_calendar():
    """ForexFactoryから今日・明日のUSD/JPY高インパクト経済指標を取得しJST変換して返す"""
    ny_tz = pytz.timezone('America/New_York')
    jst = pytz.timezone('Asia/Tokyo')
    now_jst = datetime.now(jst)

    try:
        resp = requests.get(CALENDAR_URL, timeout=10, headers=NEWS_HEADERS)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ 経済カレンダー取得エラー: {e}")
        return None

    events = []
    for ev in root.findall('event'):
        country = ev.findtext('country', '').strip()
        impact  = ev.findtext('impact', '').strip()
        if country not in CALENDAR_COUNTRIES or impact not in CALENDAR_IMPACTS:
            continue

        title    = ev.findtext('title', '').strip()
        date_str = ev.findtext('date', '').strip()
        time_str = ev.findtext('time', '').strip()
        forecast = ev.findtext('forecast', '').strip()
        previous = ev.findtext('previous', '').strip()
        actual   = ev.findtext('actual', '').strip()

        # 今日・明日のみ対象
        try:
            ev_date = datetime.strptime(date_str, "%b %d, %Y").date()
            delta = (ev_date - now_jst.date()).days
            if delta < 0 or delta > 1:
                continue
        except ValueError:
            continue

        # 時刻をJSTに変換
        time_display = ""
        if time_str and time_str not in ("All Day", "Tentative"):
            try:
                dt_ny = datetime.strptime(
                    f"{date_str} {time_str.upper()}", "%b %d, %Y %I:%M%p"
                )
                dt_ny = ny_tz.localize(dt_ny)
                dt_jst = dt_ny.astimezone(jst)
                time_display = dt_jst.strftime("%m/%d %H:%M JST")
            except ValueError:
                time_display = f"{time_str} ET"
        elif time_str:
            time_display = time_str

        icon = "🔴" if impact == "High" else "🟡"
        flag = "🇺🇸" if country == "USD" else "🇯🇵"
        line = f"{icon}{flag} {title}  {time_display}"
        if actual:
            line += f"  結果: {actual}"
        if forecast:
            line += f"  予測: {forecast}"
        if previous:
            line += f"  前回: {previous}"
        events.append(line)

    if not events:
        print("ℹ️ 経済カレンダー: 対象指標なし")
        return None

    print(f"✅ 経済カレンダー: {len(events)}件取得")
    return "\n".join(events)

# ==========================================
# 4. 市場休場チェック
# ==========================================
def get_market_status(date):
    """指定日の東証(XJPX)・NYSE(XNYS)の開場状況を返す。取得失敗時は開場扱い。"""
    date_str = date.strftime("%Y-%m-%d")
    result = {"tse_open": True, "nyse_open": True}
    try:
        result["tse_open"]  = xcals.get_calendar("XJPX").is_session(date_str)
        result["nyse_open"] = xcals.get_calendar("XNYS").is_session(date_str)
    except Exception as e:
        print(f"⚠️ 市場カレンダー取得エラー（開場扱いで続行）: {e}")
    return result

# ==========================================
# 5. 市場データ取得
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
# 6. AI分析生成 (フォールバック機能付き)
# ==========================================
def generate_analysis(market_data_str, news_str, calendar_str, nyse_notice=None, tse_open=True, force_mode=None):
    api_keys = [GEMINI_API_KEY, GEMINI_API_KEY_2]
    valid_keys = [k for k in api_keys if k]
    random.shuffle(valid_keys)

    # 試行するモデルの優先順位
    model_priority = [
        'gemini-2.5-flash', 
        'gemini-2.5-flash-lite', 
        'gemini-3.1-flash-lite-preview'
    ]

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    hour = force_mode if force_mode is not None else now.hour
    today_str = now.strftime("%Y年%m月%d日(%a)")

    # 経済カレンダーセクション
    nyse_notice_line = f"\n🔔 {nyse_notice}\n" if nyse_notice else ""
    if calendar_str:
        cal_section = f"""
【経済指標カレンダー（本日・翌日 / USD・JPY 高中インパクト）】
🔴=高インパクト  🟡=中インパクト  🇺🇸=USD  🇯🇵=JPY  時刻はJST
{nyse_notice_line}
{calendar_str}
"""
    else:
        cal_section = f"【経済指標カレンダー】本日・翌日の対象指標なし{nyse_notice_line}\n"

    # ニュースセクション
    if news_str:
        news_section = f"""
【最新ニュース（{today_str} 取得 / NHK・Reuters Japan）】
以下を一次情報として使用してください。確認されていない事象の推測や前置きは不要です。

{news_str}
"""
    else:
        news_section = "【最新ニュース】取得失敗（学習データを参考にしてください）\n"

    calendar_instruction = f"""
{cal_section}
{news_section}
【分析指示・出力順序】
出力は以下の順序で構成してください。
1. 「📰 注目ニュース・発言」：ニュースで確認された政治家・要人発言・為替介入・地政学リスクをソース名付きで箇条書き。該当なしなら省略可。
2. 「⚠️重要指標アラート」：経済カレンダーに🔴指標がある場合のみ記載。指標名・発表時刻(JST)・予測値・前回値を明示。
3. 以降、モード別の分析内容。
- 実際に暴騰・暴落が起きている場合は、銘柄/指数・値幅を具体的に記載してください。
- カレンダーやニュースに根拠のない推測・前置きは省いてください。
"""

    if 5 <= hour < 11:
        mode_title = f"🌅 【朝：日本株寄り付き戦略】{today_str}"
        prompt_content = """昨晩の米国市場と今朝の気配値から、今日の日本市場を分析してください。
- 前日のニュースや米国セクターETF(XLK/XLF/XLE)の動きから、日本の「追い風」「逆風」セクターと具体銘柄（コード付）を推論。
- 日米金利差とドル円の動向から、輸出株・内需株への影響を解説。"""
    
    elif 15 <= hour < 20:
        if tse_open:
            mode_title = f"🌆 【夕：日経総括 ＆ 欧州初動】{today_str}"
            prompt_content = """日本市場の引け状況の整理と、動き出したロンドン市場の動向を分析してください。
- 今日の日本市場の総括。どのセクターや銘柄に資金が集まったかを解説。
- 欧州市場開始後のGold(XAU/USD),US100でロンドン勢が意識しそうな節目（レジサポ）を推論。
- NY市場開場までに予想されるGold(XAU/USD),US100の短期トレンド分析。"""
        else:
            mode_title = f"🌆 【夕：欧州初動 ＆ NY開場前分析】{today_str}（日本市場休場）"
            prompt_content = """本日は日本市場が休場です。日本株の総括は不要です。ロンドン市場とNY開場前の分析に集中してください。
- 欧州市場開始後のGold(XAU/USD),US100でロンドン勢が意識しそうな節目（レジサポ）を推論。
- NY市場開場までに予想されるGold(XAU/USD),US100の短期トレンド分析。
- 日本市場休場中のドル円・クロス円の動向と、NY開場後の為替への影響を解説。"""
    
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
- 出力順序は【分析指示・出力順序】に従い、「📰 注目ニュース・発言」→「⚠️重要指標アラート」→分析本文の順を厳守すること。
- 上昇・追い風と予想する銘柄や指数には「🔥」、下落・逆風と予想するものには「🧊」のマークを必ず名称の横に付けること。
- 日本の代表的な銘柄（アドバンテスト(6857)、東京エレクトロン(8035)、三菱UFJ(8306)、トヨタ(7203)など）を積極的に選び、具体的にコード付きで解説に含めること。

【トーン＆マナー】
- 特殊記号（*や_）は絶対に使わず、プレーンテキストと絵文字のみで出力。
- 箇条書きを使い、結論から簡潔に。
- プロらしい深い洞察を含めること。
"""

    response_text = None
    for key in valid_keys:
        client = genai.Client(api_key=key)
        for m_name in model_priority:
            try:
                print(f"🔄 試行中: {m_name} (Key末尾: {key[-4:]})...")
                response = client.models.generate_content(
                    model=m_name,
                    contents=final_prompt
                )
                
                if response and response.text:
                    response_text = response.text
                    print(f"✅ AI分析生成成功! 使用モデル: {m_name} (Key末尾: {key[-4:]})")
                    break
            except Exception as e:
                print(f"⚠️ {m_name} エラー: {e}")
                time.sleep(1)
                continue
        if response_text:
            break

    if not response_text:
        raise Exception("全てのAPIキーおよびモデル候補で分析生成に失敗しました。")

    notice_header = f"\n🔔 {nyse_notice}\n" if nyse_notice else ""
    return f"{mode_title}{notice_header}\n\n{response_text}"

# ==========================================
# 7. Telegram送信（4096文字制限・自動分割対応）
# ==========================================
TELEGRAM_MAX_CHARS = 4000  # 余裕を持って4000に設定

def send_telegram(text):
    """Telegramの4096文字制限に対応して長文を自動分割して送信する"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = []
    lines = text.splitlines(keepends=True)
    current = ""
    for line in lines:
        if len(current) + len(line) > TELEGRAM_MAX_CHARS:
            if current:
                chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())

    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"✅ Telegram送信完了 ({i}/{total})")
        else:
            print(f"❌ Telegram送信エラー ({i}/{total}): {res.text}")
        if i < total:
            time.sleep(1)  # 連続送信によるレート制限を回避

# ==========================================
# 8. Webアプリ送信処理  
# ==========================================
def send_to_webapp(message):
    if not WEBAPP_URL:
        print("⚠️ WEBAPP_URL が設定されていないため、Webアプリへの送信をスキップします。")
        return
    
    payload = {"message": message}
    try:
        res = requests.post(WEBAPP_URL, json=payload, timeout=10)
        if res.status_code == 200:
            print("✅ Webアプリへの同期完了")
        else:
            print(f"❌ Webアプリ送信エラー: {res.status_code}")
    except Exception as e:
        print(f"❌ Webアプリ通信エラー: {e}")

# ==========================================
# 9. メイン処理
# ==========================================
def main():
    jst = pytz.timezone('Asia/Tokyo')
    now_jst = datetime.now(jst)
    today    = now_jst.date()
    tomorrow = today + timedelta(days=1)
    hour     = now_jst.hour

    # --- 市場休場チェック ---
    today_st = get_market_status(today)
    tmrw_st  = get_market_status(tomorrow)

    is_morning = 5  <= hour < 11
    is_evening = 15 <= hour < 20
    is_night   = not (is_morning or is_evening)

    # 朝: 東証休場 → スキップ
    if is_morning and not today_st["tse_open"]:
        print(f"ℹ️ 本日（{today}）東証休場のため朝ブリーフィングをスキップします。")
        sys.exit(0)

    # 夕: 東証・NYSE当日両方休場 → スキップ
    if is_evening and not today_st["tse_open"] and not today_st["nyse_open"]:
        print(f"ℹ️ 本日（{today}）東証・NYSE共に休場のため夕ブリーフィングをスキップします。")
        sys.exit(0)

    # 夜: NYSE休場 → スキップ
    if is_night and not today_st["nyse_open"]:
        print(f"ℹ️ 本日（{today}）NYSE休場のため夜ブリーフィングをスキップします。")
        sys.exit(0)

    # NYSE休場通知文を生成
    nyse_notice = None
    if is_morning and not today_st["nyse_open"]:
        # 朝: 当日NYSE休場
        nyse_notice = f"本日（{today.strftime('%m/%d')}）はNYSEが休場です。夜のブリーフィングはお休みします。"
    elif is_evening:
        if not today_st["nyse_open"]:
            # 夕: 当日NYSE休場（当日優先）
            nyse_notice = f"本日（{today.strftime('%m/%d')}）はNYSEが休場です。夜のブリーフィングはお休みします。"
        elif not tmrw_st["nyse_open"]:
            # 夕: 翌日NYSE休場
            nyse_notice = f"明日（{tomorrow.strftime('%m/%d')}）はNYSEが休場です。夜のブリーフィングはお休みします。"
    if nyse_notice:
        print(f"🔔 {nyse_notice}")

    try:
        market_data = get_market_data()
        news        = get_news_headlines()
        calendar    = get_economic_calendar()
        analysis    = generate_analysis(market_data, news, calendar, nyse_notice=nyse_notice, tse_open=today_st["tse_open"])

        send_telegram(f"=== Briefing ===\n{analysis}")
        send_to_webapp(analysis)

    except Exception as e:
        print(f"❌ エラー発生: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
