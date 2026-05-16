#!/usr/bin/env python3
"""
HDRezka New Movies Monitor — парсит новые фильмы через Playwright и отправляет в Telegram.
Запускается по cron (GitHub Actions) каждые 30 минут.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

STATE_FILE = Path(__file__).parent / "state.json"

DOMAINS = [
    "https://hdrezka.ag",
    "https://rezka.ag",
]

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


_BROWSER = None


def get_browser():
    global _BROWSER
    if _BROWSER is None:
        _playwright = sync_playwright().start()
        _BROWSER = _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
    return _BROWSER


def fetch_page(url: str, timeout: int = 30000) -> str:
    """Загружает страницу через Playwright (обходит Cloudflare)."""
    browser = get_browser()
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="ru-RU",
        timezone_id="Europe/Moscow",
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=timeout)
        page_title = page.title()
        print(f"  Page title: {page_title}")
        print(f"  Final URL: {page.url}")
        try:
            page.wait_for_selector('[data-id]', timeout=15000)
        except Exception:
            print(f"  No [data-id] elements found via selector")
        page.wait_for_timeout(3000)
        content = page.content()
        if not re.findall(r'data-id="(\d+)"', content):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
            content = page.content()
        body = page.evaluate("document.body.innerText")
        print(f"  Body text length: {len(body)} chars")
        print(f"  Body starts: {body[:200]}")
        return content
    finally:
        context.close()


def load_state() -> set:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("seen_ids", []))
    return set()


def save_state(seen_ids: set):
    STATE_FILE.write_text(json.dumps({"seen_ids": sorted(seen_ids)}, indent=2))


def fetch_new_films() -> list:
    last_error = None
    for domain in DOMAINS:
        url = f"{domain}/new/?filter=last&genre=1"
        try:
            print(f"  Пробуем домен: {domain}...")
            html = fetch_page(url)
            pattern = r'data-id="(\d+)"\s+data-url="(.*?)"'
            matches = re.findall(pattern, html)

            films = []
            for film_id, film_url in matches:
                films.append({
                    "id": film_id,
                    "url": film_url if film_url.startswith("http") else f"{domain}{film_url}",
                })
            print(f"  Домен работает: {domain}, найдено: {len(films)}")
            if not films:
                snippet = html[500:2500] if len(html) > 2500 else html[:1500]
                print(f"  DEBUG HTML snippet:")
                for line in snippet.split("\n")[:20]:
                    print(f"    {line.strip()[:200]}")
            return films
        except Exception as e:
            last_error = e
            print(f"  Домен {domain} не ответил: {e}")

    raise last_error or RuntimeError("All HDRezka domains failed")


def fetch_film_details(film_url: str) -> dict:
    """Заходит на страницу фильма и парсит полную информацию."""
    try:
        html = fetch_page(film_url, timeout=20000)
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""

        year = ""
        meta = soup.find("meta", property="og:title")
        if meta:
            og_content = meta.get("content", "")
            year_match = re.search(r"\((\d{4})\)", og_content)
            if year_match:
                year = year_match.group(1)

        info = {}
        table = soup.find("table", class_="b-post__info")
        if table:
            rows = table.find_all("tr")
            for row in rows:
                tds = row.find_all("td")
                if len(tds) >= 2:
                    label = tds[0].get_text(strip=True).rstrip(":")
                    value = tds[1].get_text(strip=True)
                    value = re.sub(r"Смотреть трейлер\s*", "", value).strip()
                    if label and value:
                        info[label] = value

        desc_el = soup.find("div", class_="b-post__description_text")
        description = desc_el.get_text(strip=True) if desc_el else ""
        description = re.sub(r"Смотреть трейлер\s*", "", description).strip()

        actors = []
        for actor_el in soup.find_all("span", class_="person-name-item"):
            link = actor_el.find("a")
            if link:
                span = link.find("span")
                if span:
                    actors.append(span.get_text(strip=True))

        return {
            "title": title,
            "year": year,
            "description": description,
            "info": info,
            "actors": actors,
        }
    except Exception as e:
        print(f"  Ошибка парсинга {film_url}: {e}", file=sys.stderr)
        return {"title": "", "year": "", "description": "", "info": {}, "actors": []}


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


def format_message(film: dict, description: str, info: dict, actors: list) -> str:
    year_str = f" ({film['year']})" if film["year"] else ""
    msg = f"<b>🎬 {film['title']}{year_str}</b>\n\n"

    if description:
        if len(description) > 800:
            description = description[:797] + "..."
        msg += f"{description}\n\n"

    emoji_map = {
        "Рейтинги": "⭐",
        "Дата выхода": "📅",
        "Страна": "🌍",
        "Режиссер": "🎥",
        "Жанр": "🎭",
        "В качестве": "📺",
        "В переводе": "🗣️",
        "Возраст": "🔞",
        "Время": "⏱️",
        "Из серии": "📂",
    }

    for key, emoji in emoji_map.items():
        if key in info:
            value = info[key]
            msg += f"{emoji} <b>{key}:</b> {value}\n"

    if actors:
        actors_str = ", ".join(actors[:8])
        if len(actors) > 8:
            actors_str += f" и ещё {len(actors) - 8}"
        msg += f"\n🎬 <b>В ролях:</b> {actors_str}\n"

    msg += f"\n🔗 <a href=\"{film['url']}\">Смотреть на HDRezka</a>"

    return msg


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1, help="Лимит новых фильмов за запуск (по умолчанию 1)")
    args = parser.parse_args()

    print("🔍 Проверка новых фильмов на HDRezka...")

    seen_ids = load_state()
    films = fetch_new_films()

    print(f"  Найдено фильмов: {len(films)}")
    print(f"  Уже известно: {len(seen_ids)}")

    new_films = [f for f in films if f["id"] not in seen_ids]
    print(f"  Новых: {len(new_films)}")

    if args.limit > 0:
        new_films = new_films[:args.limit]
        print(f"  Лимит: отправим {len(new_films)}")

    if not new_films:
        print("✅ Новых фильмов нет.")
        return 0

    sent_count = 0
    for i, film in enumerate(new_films, 1):
        print(f"\n  [{i}/{len(new_films)}] Загрузка страницы {film['url']}...")

        details = fetch_film_details(film["url"])
        msg = format_message({**film, **details}, details["description"], details["info"], details["actors"])

        if send_telegram(msg):
            print(f"    ✅ Отправлено: {details['title']} ({details['year']})")
            sent_count += 1
        else:
            print(f"    ❌ Ошибка отправки")

        time.sleep(1)

    all_ids = seen_ids | {f["id"] for f in films}
    save_state(all_ids)

    remaining = len([f for f in films if f["id"] not in seen_ids]) - sent_count
    if remaining > 0:
        print(f"\n⏳ Ещё {remaining} новых фильмов ждут следующего запуска")

    print(f"\n✅ Готово! Отправлено: {sent_count}/{len(new_films)}")
    return 0 if sent_count == len(new_films) else 1


if __name__ == "__main__":
    sys.exit(main())
