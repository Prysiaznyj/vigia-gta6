#!/usr/bin/env python3
"""
VIGIA // GTA VI — coletor automático de sinais.

Roda via GitHub Actions (cron). Puxa notícias (Google News RSS), posts em alta
do Reddit (r/GTA6) e, se houver YOUTUBE_API_KEY, vídeos recentes no YouTube.
Classifica, pontua e escreve data.json na raiz do site.

Se ANTHROPIC_API_KEY estiver definida, usa a API da Anthropic pra reescrever
headline/desc/hook no tom do canal (mesmo estilo dos cards feitos à mão).
Sem a chave, usa um gerador de hook por template — mais cru, mas funcional.
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
import requests

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data.json")
DATA_FILE = os.path.abspath(DATA_FILE)
MAX_ITEMS = 40
LOOKBACK_HOURS = 72
UA = "vigia-gta6-bot/1.0 (+https://github.com/)"

NEWS_QUERIES = [
    "GTA 6",
    "GTA VI Rockstar",
    "GTA 6 leak OR rumor",
    "GTA 6 Take-Two",
    "Rockstar Games union OR crunch",
    "GTA 6 preço OR price OR sales",
]

CATEGORY_RULES = [
    ("trabalhista", [r"\bunion\b", r"sindicat", r"crunch", r"trabalhist", r"strike", r"greve"]),
    ("vendas", [r"pre-?order", r"\bsales\b", r"\bvendas\b", r"\bpre[çc]o\b", r"\bprice\b", r"record"]),
    ("lancamento", [r"release date", r"\bdelay", r"\btrailer\b", r"\blaunch\b", r"lan[çc]amento", r"adiad"]),
    ("boatos", [r"\brumor", r"\bleak", r"insider", r"boato", r"vazament", r"reportedly", r"apparently"]),
]

CAT_TAG_LABEL = {
    "lancamento": "Lançamento",
    "trabalhista": "Trabalhista",
    "vendas": "Vendas & Preço",
    "boatos": "Boatos",
    "curiosidade": "Curiosidade",
    "viral": "Viral",
}

HOOK_TEMPLATES = {
    "lancamento": "Abre direto com '{headline}' e mostra a fonte na tela — bom gancho de atualização de linha do tempo.",
    "trabalhista": "Ângulo bastidores: '{headline}' — contraste com o hype do lançamento.",
    "vendas": "Número na cara logo na primeira frase: '{headline}' — formato \"isso é muito ou pouco?\".",
    "boatos": "Pergunta de abertura: '{headline}?' — deixa claro que é especulação, mas prende pela dúvida.",
    "curiosidade": "Curiosidade rápida: '{headline}' — bom pra fechar um vídeo ou virar corte solto.",
    "viral": "Mostra o clipe/post que tá bombando ('{headline}') e reage em cima — aproveita o algoritmo já aquecido.",
}


def load_existing():
    if not os.path.exists(DATA_FILE):
        return {"updated": "", "items": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return set(text.split())


def is_duplicate(headline, seen_token_sets, threshold=0.6):
    tokens = normalize(headline)
    if not tokens:
        return False
    for existing in seen_token_sets:
        if not existing:
            continue
        overlap = len(tokens & existing) / max(1, min(len(tokens), len(existing)))
        if overlap >= threshold:
            return True
    return False


def classify(text):
    low = text.lower()
    for cat, patterns in CATEGORY_RULES:
        for p in patterns:
            if re.search(p, low):
                return cat
    return None  # decidido depois pela origem (reddit/youtube -> viral, senão curiosidade)


def score_item(recency_hours, engagement, keyword_bonus):
    s = 1
    if recency_hours <= 6:
        s += 2
    elif recency_hours <= 24:
        s += 1
    if engagement >= 5000:
        s += 2
    elif engagement >= 500:
        s += 1
    s += keyword_bonus
    return max(1, min(5, s))


def fetch_news():
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for q in NEWS_QUERIES:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[news] falhou '{q}': {e}", file=sys.stderr)
            continue
        for entry in feed.entries[:12]:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                published = datetime.now(timezone.utc)
            if published < cutoff:
                continue
            title = re.sub(r"\s*-\s*[^-]+$", "", entry.title)  # tira " - Fonte" do fim
            items.append({
                "source": "news",
                "headline": title,
                "desc": getattr(entry, "summary", "")[:280],
                "url": entry.link,
                "published": published,
                "engagement": 0,
                "keyword_bonus": 1 if re.search(r"confirm|official|oficial", title.lower()) else 0,
            })
    return items


def fetch_reddit():
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for listing in ("hot", "new"):
        url = f"https://www.reddit.com/r/GTA6/{listing}.json?limit=20"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
            r.raise_for_status()
            posts = r.json()["data"]["children"]
        except Exception as e:
            print(f"[reddit] falhou '{listing}': {e}", file=sys.stderr)
            continue
        for p in posts:
            d = p["data"]
            published = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
            if published < cutoff:
                continue
            score = d.get("score", 0)
            comments = d.get("num_comments", 0)
            items.append({
                "source": "reddit",
                "headline": d.get("title", ""),
                "desc": (d.get("selftext") or "")[:280] or f"Post em alta no r/GTA6 ({score} upvotes, {comments} comentários).",
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "published": published,
                "engagement": score + comments * 3,
                "keyword_bonus": 0,
            })
    return items


def fetch_youtube():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("[youtube] YOUTUBE_API_KEY não definida, pulando.", file=sys.stderr)
        return []
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": "GTA 6",
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": 15,
                "key": key,
            },
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("items", [])
    except Exception as e:
        print(f"[youtube] falhou: {e}", file=sys.stderr)
        return []

    video_ids = [it["id"]["videoId"] for it in results if it.get("id", {}).get("videoId")]
    stats = {}
    if video_ids:
        try:
            r2 = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics", "id": ",".join(video_ids), "key": key},
                timeout=15,
            )
            r2.raise_for_status()
            for v in r2.json().get("items", []):
                stats[v["id"]] = int(v.get("statistics", {}).get("viewCount", 0))
        except Exception as e:
            print(f"[youtube stats] falhou: {e}", file=sys.stderr)

    for it in results:
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        snippet = it["snippet"]
        try:
            published = datetime.strptime(snippet["publishedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        views = stats.get(vid, 0)
        items.append({
            "source": "youtube",
            "headline": snippet.get("title", ""),
            "desc": (snippet.get("description") or "")[:280] or f"Vídeo em alta sobre GTA 6 ({views} views).",
            "url": f"https://youtube.com/watch?v={vid}",
            "published": published,
            "engagement": views,
            "keyword_bonus": 0,
        })
    return items


def maybe_rewrite_with_claude(raw_items):
    """Se ANTHROPIC_API_KEY existir, reescreve headline/desc/hook no tom do canal."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not raw_items:
        return None
    prompt_items = [
        {"headline": it["headline"], "desc": it["desc"], "cat": it["cat"]}
        for it in raw_items
    ]
    prompt = (
        "Você escreve pro canal de conteúdo 'Sem Missão', focado em GTA 6. "
        "Reescreva cada item abaixo em PT-BR, tom direto de criador, nada corporativo. "
        "Para cada item retorne: headline (uma frase chamativa), desc (1-2 frases factuais), "
        "hook (sugestão concreta de gancho pra abrir um vídeo curto sobre o assunto). "
        "Responda em JSON: lista de objetos com headline, desc, hook, na MESMA ORDEM da entrada.\n\n"
        f"ITENS:\n{json.dumps(prompt_items, ensure_ascii=False, indent=2)}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-5",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"]
        match = re.search(r"\[.*\]", text, re.DOTALL)
        rewritten = json.loads(match.group(0)) if match else None
        if rewritten and len(rewritten) == len(raw_items):
            return rewritten
    except Exception as e:
        print(f"[claude rewrite] falhou, usando fallback: {e}", file=sys.stderr)
    return None


def build_items():
    raw = fetch_news() + fetch_reddit() + fetch_youtube()
    raw.sort(key=lambda x: x["published"], reverse=True)

    existing = load_existing()
    seen_tokens = [normalize(it["headline"]) for it in existing.get("items", [])]

    deduped = []
    for it in raw:
        if is_duplicate(it["headline"], seen_tokens):
            continue
        seen_tokens.append(normalize(it["headline"]))
        deduped.append(it)

    classified = []
    for it in deduped:
        cat = classify(it["headline"] + " " + it["desc"])
        if not cat:
            cat = "viral" if it["source"] in ("reddit", "youtube") else "curiosidade"
        recency_hours = (datetime.now(timezone.utc) - it["published"]).total_seconds() / 3600
        signal = score_item(recency_hours, it["engagement"], it["keyword_bonus"])
        classified.append({
            "cat": cat,
            "tagLabel": CAT_TAG_LABEL[cat],
            "date": it["published"].strftime("%d/%m/%Y"),
            "headline": it["headline"].strip(),
            "desc": it["desc"].strip() or "Sem descrição disponível — ver fonte.",
            "signal": signal,
            "hook": HOOK_TEMPLATES[cat].format(headline=it["headline"].strip()),
            "url": it["url"],
        })

    # tenta melhorar texto com Claude, se configurado
    rewritten = maybe_rewrite_with_claude(classified)
    if rewritten:
        for orig, new in zip(classified, rewritten):
            orig["headline"] = new.get("headline", orig["headline"])
            orig["desc"] = new.get("desc", orig["desc"])
            orig["hook"] = new.get("hook", orig["hook"])

    return classified


def main():
    existing = load_existing()
    new_items = build_items()

    combined = new_items + existing.get("items", [])
    # nunca derruba itens de alto sinal em categorias-chave; corta o resto se passar do limite
    if len(combined) > MAX_ITEMS:
        protected = [it for it in combined if it["cat"] in ("lancamento", "trabalhista", "vendas") and it["signal"] >= 5]
        rest = [it for it in combined if it not in protected]
        rest.sort(key=lambda x: x["signal"], reverse=True)
        combined = protected + rest
        combined = combined[:MAX_ITEMS]

    out = {
        "updated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "items": combined,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"OK — {len(new_items)} itens novos, {len(combined)} no total.")


if __name__ == "__main__":
    main()
