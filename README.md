# HDRezka New Movies Monitor

Telegram-бот для мониторинга новых фильмов на HDRezka. Автоматически отслеживает новые релизы и отправляет уведомления в Telegram.

## Возможности

- 🔍 Автоматический мониторинг новых фильмов на HDRezka каждые 30 минут
- 📝 Отправляет описание, жанр и ссылку на каждый новый фильм
- 🚫 Без повторов — каждый фильм отправляется один раз
- ⏰ Работает на GitHub Actions (бесплатно, без своего сервера)

## Как работает

1. GitHub Actions запускает скрипт каждые 30 минут
2. Скрипт парсит `rezka.ag/new/?filter=last&genre=1` (только фильмы)
3. Сравнивает film_id с `state.json` — находит новые
4. Для каждого нового фильма заходит на страницу, берёт описание
5. Отправляет сообщение в Telegram
6. Обновляет `state.json`

## Пример сообщения

```
🎬 Мы умрём сегодня ночью (2025)

Когда-то Ян был полицейским под прикрытием...

🎭 Триллеры, Швеция

🔗 Смотреть на HDRezka
```

## Настройка

### 1. Создать Telegram-бота

- Написать [@BotFather](https://t.me/botfather)
- Отправить `/newbot`, следовать инструкциям
- Скопировать `BOT_TOKEN`

### 2. Узнать Chat ID

- Открыть бота в Telegram, отправить `/start`
- Открыть: `https://api.telegram.org/bot<TOKEN>/getUpdates`
- Найти `"chat":{"id":123456789,...}` — это ваш `CHAT_ID`

### 3. Добавить секреты в GitHub

```bash
gh secret set BOT_TOKEN --body "ваш-токен" --repo Alexhohner2024/hdrezka-digest
gh secret set CHAT_ID --body "ваш-chat-id" --repo Alexhohner2024/hdrezka-digest
```

### 4. Запуск

- **Автоматически:** каждые 30 минут через GitHub Actions
- **Вручную:** Actions → HDRezka New Movies Monitor → Run workflow
- **Локально:** `python3 fetch_new.py --limit 1`

## Структура проекта

```
├── fetch_new.py              # Основной скрипт
├── state.json                # Хранит увиденные film_id (авто)
├── requirements.txt          # Python зависимости
├── config.example.py         # Пример конфига
└── .github/workflows/
    └── digest.yml            # GitHub Actions (cron: */30)
```

## Зависимости

```
requests>=2.31.0
beautifulsoup4>=4.12.0
```

## Лицензия

MIT
