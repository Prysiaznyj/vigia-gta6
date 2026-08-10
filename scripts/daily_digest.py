#!/usr/bin/env python3
"""
VIGIA // GTA VI — resumo diário via Telegram.

Roda 1x/dia via GitHub Actions (cron). Lê o data.json já gerado pelo
fetch_signals.py (não importa nem modifica esse script), seleciona os
sinais fortes das últimas 24h e manda um empurrão curado pro Telegram —
o arquivo completo de tudo que a ferramenta encontra fica por conta do
arquivamento no Notion que já roda a cada varredura de 4h, direto no
fetch_signals.py (não é responsabilidade deste script).

TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID são opcionais — sem elas o script sai
sem fazer nada.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data.json")
DATA_FILE = os.path.abspath(DATA_FILE)
DIGEST_SENT_FILE = os.path.join(os.path.dirname(__file__), "..", "digest_sent.json")
DIGEST_SENT_FILE = os.path.abspath(DIGEST_SENT_FILE)

LOOKBACK_HOURS = 24
MIN_SIGNAL = 4
MAX_ITEMS = 3
SENT_RETENTION_DAYS = 3


def load_items():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[digest] falhou ler {DATA_FILE}: {e}", file=sys.stderr)
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def load_sent():
    if not os.path.exists(DIGEST_SENT_FILE):
        return {}
    try:
        with open(DIGEST_SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[digest] falhou ler {DIGEST_SENT_FILE}: {e}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_sent(sent):
    with open(DIGEST_SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False, indent=2)


def prune_sent(sent):
    """Remove entradas com mais de SENT_RETENTION_DAYS dias — o suficiente
    pra nunca colidir com a janela de 24h, sem crescer sem limite."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SENT_RETENTION_DAYS)
    kept = {}
    for url, sent_at in sent.items():
        try:
            if datetime.fromisoformat(sent_at) >= cutoff:
                kept[url] = sent_at
        except Exception:
            continue
    return kept


def select_digest_items(items, sent):
    """Filtra por janela de 24h + sinal mínimo, tira quem já foi enviado,
    ordena por sinal (desempate por mais recente) e corta em MAX_ITEMS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    candidates = []
    seen_urls = set()
    for it in items:
        published_at = it.get("publishedAt")
        if not published_at:
            continue
        try:
            published = datetime.fromisoformat(published_at)
            if published < cutoff:
                continue
        except Exception:
            continue
        if (it.get("signal") or 0) < MIN_SIGNAL:
            continue
        url = it.get("url")
        if not url or url in sent or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append((published, it))
    candidates.sort(key=lambda pair: (pair[1]["signal"], pair[0]), reverse=True)
    return [it for _, it in candidates[:MAX_ITEMS]]


TELEGRAM_API_BASE = "https://api.telegram.org"


def _escape_html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_telegram_message(items):
    lines = ["<b>🎯 Resumo de hoje — VIGIA GTA VI</b>", ""]
    for i, item in enumerate(items, start=1):
        headline = _escape_html(item.get("headline", ""))
        hook = _escape_html(item.get("hook", ""))
        url = item.get("url", "")
        lines.append(f"{i}. <b>{headline}</b>")
        lines.append(hook)
        if url:
            lines.append(f'<a href="{_escape_html(url)}">ver fonte</a>')
        lines.append("")
    return "\n".join(lines).strip()


def send_to_telegram(text, bot_token, chat_ids):
    """Manda a mesma mensagem pra cada chat_id da lista. Retorna True se
    pelo menos um envio funcionou; nunca lança."""
    any_ok = False
    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
        try:
            r = requests.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            r.raise_for_status()
            any_ok = True
        except Exception as e:
            print(f"[digest] falhou mandar Telegram pro chat_id {chat_id}: {e}", file=sys.stderr)
    return any_ok


def main():
    items = load_items()
    sent = prune_sent(load_sent())
    selected = select_digest_items(items, sent)

    if not selected:
        print("[digest] nenhum item qualificado nas últimas 24h, nada a enviar.")
        save_sent(sent)
        return

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_ids = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not (telegram_token and telegram_chat_ids):
        print("[digest] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos, nada a fazer.", file=sys.stderr)
        return

    message = build_telegram_message(selected)
    telegram_ok = send_to_telegram(message, telegram_token, telegram_chat_ids.split(","))

    if not telegram_ok:
        print("[digest] Telegram falhou — nada foi entregue. Itens NÃO marcados como enviados (tentativa de novo na próxima rodada).", file=sys.stderr)
        sys.exit(1)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in selected:
        sent[item["url"]] = now_iso
    save_sent(sent)

    print(f"OK — {len(selected)} item(ns) no resumo de hoje.")


if __name__ == "__main__":
    main()
