# Telegram Crypto Bot (Binance → Telegram)

Բոտ, который:
- берёт топ-10 криптовалют с Binance (пары с USDT),
- показывает цену в USD и в армянских драмах (AMD),
- отправляет красивые сообщения в Telegram,
- под каждым блоком из 5 монет рисует графики за 24 часа.

## Как запустить локально

1. Клонируй репозиторий или скопируй файлы:

   - `bot.py`
   - `requirements.txt`
   - `nixpacks.toml`
   - `.gitignore`

2. Установи зависимости:

   ```bash
   pip install -r requirements.txt
