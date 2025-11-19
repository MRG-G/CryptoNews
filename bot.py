import os
import time
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ======================================
# НАСТРОЙКИ
# ======================================

# Теперь берем токен и ID чата из переменных окружения,
# чтобы их НЕ хранить в GitHub.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8506148160:AAFPzNd81beUz62vxJUcUR5GWA7K1SS10pA")   # задашь на Railway
CHANNEL_ID = os.getenv("CHANNEL_ID", "@cryptoamnews")           # задашь на Railway

CACHE_FILE = "price_cache.json"

TOP_N = 10                 # теперь показываем ТОП-10 монет
BASE_QUOTE = "USDT"        # базовая котировка
FAVORITE_SYMBOL = "BTCUSDT"  # твой "любимый" коин, который всегда должен быть в списке

UPDATE_INTERVAL = 60       # период обновления в секундах

BINANCE_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
USD_AMD_URL = "https://open.er-api.com/v6/latest/USD"

TIMEZONE = ZoneInfo("Asia/Yerevan")

# HTTP сесcия
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BinanceTelegramBot/1.2"})

# Кэш klines (уменьшаем запросы к Binance)
KLINES_CACHE = {}
KLINES_LAST_FETCH = {}
KLINES_TTL = 5 * 60  # 5 минут

# ======================================
# ВСПОМОГАТЕЛЬНЫЕ HTTP-ФУНКЦИИ
# ======================================

def http_get(url, params=None, timeout=10):
    """Безопасный GET с обработкой ошибок."""
    try:
        resp = SESSION.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.RequestException as e:
        print(f"[HTTP ERROR] {url} | {e}")
        return None

# ======================================
# КЭШ ЦЕН
# ======================================

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[CACHE] Ошибка чтения кэша:", e)
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        print("[CACHE] Ошибка записи кэша:", e)

def add_to_cache(cache, symbol, price, now_ts):
    """Добавляем текущую цену в кэш, чистим историю старше 7 дней."""
    if symbol not in cache:
        cache[symbol] = []
    cache[symbol].append({"t": now_ts, "p": price})

    cutoff = now_ts - 7 * 86400
    cache[symbol] = [x for x in cache[symbol] if x["t"] >= cutoff]

def get_price_change(cache, symbol, now_ts, window_sec):
    """Процентное изменение относительно цены window_sec назад по данным кэша."""
    if symbol not in cache:
        return None

    target = now_ts - window_sec
    history = cache[symbol]
    ref = None

    for h in history:
        if h["t"] <= target:
            if not ref or h["t"] > ref["t"]:
                ref = h

    if not ref:
        return None

    old = ref["p"]
    if old == 0:
        return None

    current = history[-1]["p"]
    return (current - old) / old * 100.0

# ======================================
# ФОРМАТИРОВАНИЕ
# ======================================

def format_percent(v):
    return "—" if v is None else f"{v:+.2f}%"

def format_price_usdt(p):
    if p >= 1000:
        return f"{p:,.2f}".replace(",", " ")
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.8f}".rstrip("0").rstrip(".")

def arrow(v):
    if v is None:
        return "➖"
    return "🟢⬆️" if v > 0 else "🔴⬇️"

RANK_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

def rank_emoji(rank):
    if 1 <= rank <= 10:
        return RANK_EMOJIS[rank - 1]
    return f"{rank}."

def human_symbol(symbol):
    """BTCUSDT -> BTC/USDT."""
    if BASE_QUOTE and symbol.endswith(BASE_QUOTE):
        base = symbol[:-len(BASE_QUOTE)]
        return f"{base}/{BASE_QUOTE}"
    return symbol

def now_local_str():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M %Z")

# ======================================
# КУРС AMD
# ======================================

def get_amd_rate():
    resp = http_get(USD_AMD_URL, timeout=10)
    if not resp:
        return None
    try:
        data = resp.json()
        return float(data["rates"]["AMD"])
    except Exception as e:
        print("[AMD] Ошибка парсинга курса:", e)
        return None

# ======================================
# BINANCE DATA
# ======================================

def get_binance_tickers():
    resp = http_get(BINANCE_24HR_URL, timeout=10)
    if not resp:
        return None
    try:
        return resp.json()
    except Exception as e:
        print("[BINANCE] Ошибка парсинга тикеров:", e)
        return None

def get_klines(symbol, interval="1h", limit=24):
    """Берём klines из кэша, если не старше KLINES_TTL, иначе запрашиваем Binance."""
    key = (symbol, interval, limit)
    now_ts = time.time()
    last = KLINES_LAST_FETCH.get(key)

    if last is not None and (now_ts - last) < KLINES_TTL and key in KLINES_CACHE:
        return KLINES_CACHE[key]

    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = http_get(BINANCE_KLINES_URL, params=params, timeout=10)
    if not resp:
        return None
    try:
        data = resp.json()
        KLINES_CACHE[key] = data
        KLINES_LAST_FETCH[key] = now_ts
        return data
    except Exception as e:
        print(f"[BINANCE] Ошибка парсинга klines для {symbol}:", e)
        return None

# ======================================
# ТЕЛЕГРАМ
# ======================================

# inline-кнопка "Открыть Binance"
REPLY_MARKUP = json.dumps({
    "inline_keyboard": [
        [
            {
                "text": "🌐 Открыть Binance",
                "url": "https://www.binance.com"
            }
        ]
    ]
})

def send_message(text):
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("[TG] TELEGRAM_TOKEN или CHANNEL_ID не заданы")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        SESSION.post(
            url,
            data={
                "chat_id": CHANNEL_ID,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": REPLY_MARKUP,
            },
            timeout=10
        )
    except requests.exceptions.RequestException as e:
        print("[TG] Ошибка отправки сообщения:", e)

def send_photo(filename, caption):
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("[TG] TELEGRAM_TOKEN или CHANNEL_ID не заданы")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(filename, "rb") as f:
            SESSION.post(
                url,
                data={
                    "chat_id": CHANNEL_ID,
                    "caption": caption,
                    "parse_mode": "Markdown",
                    "reply_markup": REPLY_MARKUP,
                },
                files={"photo": f},
                timeout=20
            )
    except Exception as e:
        print("[TG] Ошибка отправки фото:", e)

# ======================================
# ГРАФИКИ
# ======================================

def draw_chart(symbol, klines, filename="chart.png"):
    prices = [float(k[4]) for k in klines]  # close price
    x = range(len(prices))

    plt.figure(figsize=(6, 3))
    plt.plot(x, prices, linewidth=2)
    plt.grid(True, alpha=0.3)
    plt.title(f"{human_symbol(symbol)} • 24h chart")
    plt.xlabel("Свечи (1ч)")
    plt.ylabel("Цена")

    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close()

# ======================================
# ТЕКСТ ДЛЯ БЛОКА ИЗ 5 МОНЕТ
# ======================================

def build_block(coins, cache, amd_rate, block_index, total_blocks, start_rank):
    """
    coins        — список из максимум 5 монет
    start_rank   — глобальный номер первой монеты в этом блоке (1, 6, ...)
    """
    lines = []

    header = (
        "📊 *ТОП КРИПТО (Binance)*\n"
        f"_Թարմացվել է / Обновлено:_ {now_local_str()}\n"
        f"Блок *{block_index}* из *{total_blocks}*\n\n"
    )
    lines.append(header)

    now_ts = time.time()
    rank = start_rank

    for coin in coins:
        symbol = coin["symbol"]
        nice_symbol = human_symbol(symbol)

        price = float(coin["lastPrice"])
        ch24 = float(coin["priceChangePercent"])

        # кэш для 1м/1ч/7д
        add_to_cache(cache, symbol, price, now_ts)

        ch1m = get_price_change(cache, symbol, now_ts, 60)
        ch1h = get_price_change(cache, symbol, now_ts, 3600)
        ch7d = get_price_change(cache, symbol, now_ts, 7 * 86400)

        price_usdt = format_price_usdt(price)

        # пересчёт в AMD
        if amd_rate:
            price_amd_val = int(price * amd_rate)
            price_amd_str = f"{price_amd_val:,}".replace(",", " ")
        else:
            price_amd_str = "—"

        r_emoji = rank_emoji(rank)

        # текст: сколько долларов и сколько драм — + на армянском
        line = (
            f"{r_emoji} *{nice_symbol}*\n"
            f"💵 Цена (USD): `{price_usdt} $`\n"
            f"🇦🇲 Գին դրամով: `{price_amd_str} դր`\n"
            f"📊 Դինամիկա / Движение:\n"
            f"{arrow(ch1m)} 1 րոպե / 1м: {format_percent(ch1m)}   "
            f"{arrow(ch1h)} 1 ժամ / 1ч: {format_percent(ch1h)}\n"
            f"{arrow(ch24)} 24 ժամ / 24ч: {format_percent(ch24)}   "
            f"{arrow(ch7d)} 7 օր / 7д: {format_percent(ch7d)}\n"
            "----------------------------------------------"
        )

        lines.append(line)
        rank += 1

    return "\n".join(lines)

# ======================================
# УТИЛИТА ДЛЯ РАЗБИЕНИЯ НА ГРУППЫ ПО 5
# ======================================

def chunked(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

# ======================================
# MAIN
# ======================================

def main():
    cache = load_cache()
    print("Бот запущен.")
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("[WARN] TELEGRAM_TOKEN или CHANNEL_ID не заданы! Сообщения отправляться не будут.")

    while True:
        try:
            tickers = get_binance_tickers()
            if not tickers:
                print("[MAIN] Не удалось получить данные с Binance, ждем и пробуем снова.")
                time.sleep(UPDATE_INTERVAL)
                continue

            # все пары с нужной котировкой
            pairs = [t for t in tickers if t["symbol"].endswith(BASE_QUOTE)]

            # сортируем по объёму
            pairs.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)

            # формируем список из TOP_N монет:
            # 1) любимая пара
            # 2) остальные топовые по объёму, пока не наберём TOP_N
            top = []
            favorite = next((t for t in pairs if t["symbol"] == FAVORITE_SYMBOL), None)
            if favorite:
                top.append(favorite)

            for t in pairs:
                if len(top) >= TOP_N:
                    break
                if favorite and t["symbol"] == FAVORITE_SYMBOL:
                    continue
                top.append(t)

            if not top:
                print("[MAIN] Нет пар для отображения.")
                time.sleep(UPDATE_INTERVAL)
                continue

            # курс AMD
            amd_rate = get_amd_rate()

            # делим на блоки по 5 монет
            groups = chunked(top, 5)
            total_blocks = len(groups)

            current_rank = 1

            for block_index, group in enumerate(groups, start=1):
                # текстовый блок для этих 5 монет
                block_text = build_block(
                    coins=group,
                    cache=cache,
                    amd_rate=amd_rate,
                    block_index=block_index,
                    total_blocks=total_blocks,
                    start_rank=current_rank,
                )

                # отправляем текст сообщения
                send_message(block_text)
                time.sleep(1)

                # под текстом — графики для каждой монеты в блоке
                for coin in group:
                    symbol = coin["symbol"]
                    kl = get_klines(symbol, "1h", 24)
                    if not kl:
                        print(f"[MAIN] Нет данных klines для {symbol}")
                        continue

                    filename = f"chart_{symbol}.png"
                    draw_chart(symbol, kl, filename)
                    caption = f"📈 *{human_symbol(symbol)}* — график за 24 часа"
                    send_photo(filename, caption)
                    time.sleep(1)

                current_rank += len(group)

            # сохраняем кэш после обработки всех блоков
            save_cache(cache)

        except Exception as e:
            print("[MAIN] Ошибка в цикле:", e)

        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    main()
