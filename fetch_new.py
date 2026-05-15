#!/usr/bin/env python3
"""
HDRezka Daily Digest — парсит новые фильмы и отправляет в Telegram.
Запускается по cron (GitHub Actions) каждый день в 19:00 EET.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path(__file__).parent / "state.json"
REZKA_NEW_URL = "https://rezka.ag/new/?filter=last&genre=1"
REZKA_BASE = "https://rezka.ag"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def load_state() -> set:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("seen_ids", []))
    return set()


def save_state(seen_ids: set):
    STATE_FILE.write_text(json.dumps({"seen_ids": sorted(seen_ids)}, indent=2))


def fetch_new_films() -> list:
    resp = requests.get(REZKA_NEW_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    pattern = r'data-id="(\d+)"\s+data-url="(.*?)"'
    matches = re.findall(pattern, resp.text)

    films = []
    for film_id, film_url in matches:
        # Извлекаем название из URL
        slug = film_url.rstrip(".html").split("/")[-1]
        # Убираем год в конце
        title_match = re.match(r"(.+?)-(\d{4})$", slug)
        if title_match:
            title = title_match.group(1).replace("-", " ").capitalize()
            year = title_match.group(2)
        else:
            title = slug.replace("-", " ").capitalize()
            year = ""

        films.append({
            "id": film_id,
            "title": title,
            "year": year,
            "url": film_url if film_url.startswith("http") else f"{REZKA_BASE}{film_url}",
        })

    return films


def fetch_film_description(film_url: str) -> tuple:
    """Заходит на страницу фильма и парсит описание + жанр."""
    try:
        resp = requests.get(film_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Описание
        desc_el = soup.find("div", class_="b-post__description_text")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Жанр / страна из мета-информации
        info_div = soup.find("div", class_="b-post__info")
        genre = ""
        if info_div:
            genre_spans = info_div.find_all("span", class_="ellipsis")
            if genre_spans:
                genre = ", ".join(s.get_text(strip=True) for s in genre_spans[:3])

        # Если не нашли через b-post__info, пробуем альтернативу
        if not genre:
            genre_div = soup.find("div", class_="b-post__origtitle")
            if genre_div:
                next_div = genre_div.find_next_sibling("div")
                if next_div:
                    genre = next_div.get_text(strip=True)[:100]

        return description, genre
    except Exception as e:
        print(f"  Ошибка парсинга {film_url}: {e}", file=sys.stderr)
        return "", ""


def send_telegram(text: str) -> bool:
    """Отправляет сообщение в Telegram."""
    try:
        resp = requests.post(TELEGRAM_URL, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }, timeout=15)
        result = resp.json()
        if not result.get("ok"):
            print(f"  Telegram error: {result.get('description', 'unknown')}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  Telegram send error: {e}", file=sys.stderr)
        return False


def format_message(film: dict, description: str, genre: str) -> str:
    year_str = f" ({film['year']})" if film["year"] else ""
    msg = f"<b>🎬 {film['title']}{year_str}</b>\n\n"

    if description:
        # Обрезаем до 800 символов (лимит Telegram ~4096, но лучше короче)
        if len(description) > 800:
            description = description[:797] + "..."
        msg += f"{description}\n\n"

    if genre:
        msg += f"🎭 {genre}\n"

    msg += f"\n🔗 <a href=\"{film['url']}\">Смотреть на HDRezka</a>"

    return msg


def main():
    print("🔍 Проверка новых фильмов на HDRezka...")

    seen_ids = load_state()
    films = fetch_new_films()

    print(f"  Найдено фильмов: {len(films)}")
    print(f"  Уже известно: {len(seen_ids)}")

    new_films = [f for f in films if f["id"] not in seen_ids]
    print(f"  Новых: {len(new_films)}")

    if not new_films:
        print("✅ Новых фильмов нет.")
        return 0

    sent_count = 0
    for i, film in enumerate(new_films, 1):
        print(f"\n  [{i}/{len(new_films)}] {film['title']} ({film['year']})")

        description, genre = fetch_film_description(film["url"])
        msg = format_message(film, description, genre)

        if send_telegram(msg):
            print(f"    ✅ Отправлено в Telegram")
            sent_count += 1
        else:
            print(f"    ❌ Ошибка отправки")

        # Небольшая задержка между запросами
        time.sleep(1)

    # Обновляем state
    all_ids = seen_ids | {f["id"] for f in films}
    save_state(all_ids)

    print(f"\n✅ Готово! Отправлено: {sent_count}/{len(new_films)}")
    return 0 if sent_count == len(new_films) else 1


if __name__ == "__main__":
    sys.exit(main())
