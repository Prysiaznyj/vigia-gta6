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
import html
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import statistics

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data.json")
DATA_FILE = os.path.abspath(DATA_FILE)
MAX_ITEMS = 60
LOOKBACK_HOURS = 72
UA = "vigia-gta6-bot/1.0 (+https://github.com/)"
CHANNEL_BASELINE_FILE = os.path.join(os.path.dirname(__file__), "..", "channel_baselines.json")
CHANNEL_BASELINE_FILE = os.path.abspath(CHANNEL_BASELINE_FILE)
HOT_WINDOW_HOURS = 4
HOT_TOP_N = 6
BASELINE_MAX_AGE_HOURS = 24
BASELINE_MIN_SAMPLE = 3
OUTLIER_CHANNEL_MULTIPLIER = 2
MIN_NEWS = 10
MIN_VIDEO_LONGO = 10
MIN_VIDEO_CURTO = 10

NEWS_LOCALES = [
    ("pt", "pt-BR", "BR", "BR:pt-419", [
        "GTA 6",
        "GTA VI Rockstar",
        "GTA 6 leak OR rumor",
        "GTA 6 Take-Two",
        "Rockstar Games union OR crunch",
        "GTA 6 preço OR price OR sales",
    ]),
    ("en", "en-US", "US", "US:en", [
        "GTA 6",
        "GTA VI Rockstar",
        "GTA 6 leak OR rumor",
        "GTA 6 Take-Two",
        "Rockstar Games union OR crunch",
        "GTA 6 price OR sales OR delay",
    ]),
    ("es", "es-419", "MX", "MX:es-419", [
        "GTA 6",
        "GTA VI Rockstar",
        "GTA 6 filtracion OR rumor",
        "GTA 6 Take-Two",
        "Rockstar Games sindicato OR huelga",
        "GTA 6 precio OR retraso",
    ]),
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
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[data] falhou ler {DATA_FILE}, começando do zero: {e}", file=sys.stderr)
        return {"updated": "", "items": []}
    if not isinstance(data, dict) or "items" not in data:
        return {"updated": "", "items": []}
    return data


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


def score_item(recency_hours, engagement, keyword_bonus, outlier=False):
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
    if outlier:
        s += 2
    return max(1, min(5, s))


def fetch_news():
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for lang, hl, gl, ceid, queries in NEWS_LOCALES:
        lang_count = 0
        for q in queries:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl={hl}&gl={gl}&ceid={ceid}"
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                print(f"[news] falhou '{q}' ({lang}): {e}", file=sys.stderr)
                continue
            if not feed.entries:
                print(f"[news] '{q}' ({lang}) voltou sem entradas — status={getattr(feed, 'status', '?')} bozo={getattr(feed, 'bozo', 0)} bozo_exception={getattr(feed, 'bozo_exception', None)}", file=sys.stderr)
            for entry in feed.entries[:12]:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    published = datetime.now(timezone.utc)
                if published < cutoff:
                    continue
                source_match = re.search(r"\s*-\s*([^-]+)$", entry.title)
                source_name = source_match.group(1).strip() if source_match else "Google News"
                title = re.sub(r"\s*-\s*[^-]+$", "", entry.title)  # tira " - Fonte" do fim
                items.append({
                    "source": "news",
                    "newsLang": lang,
                    "headline": title,
                    "desc": f"Fonte: {source_name}",
                    "url": entry.link,
                    "published": published,
                    "engagement": 0,
                    "keyword_bonus": 1 if re.search(r"confirm|official|oficial", title.lower()) else 0,
                })
                lang_count += 1
        print(f"[news] {lang}: {lang_count} itens dentro da janela de {LOOKBACK_HOURS}h", file=sys.stderr)
    return items


def _strip_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_reddit_summary(html):
    text = re.sub(r"submitted by.*$", "", html or "", flags=re.DOTALL)
    return _strip_html(text)


def fetch_reddit():
    """Os endpoints JSON do Reddit (.json, oauth.reddit.com) bloqueiam com 403
    requisições vindas de IPs de datacenter (caso do GitHub Actions). O feed
    RSS/Atom (.rss) responde normal, sem autenticação — só não traz contagem de
    upvotes/comentários, então usamos a posição no ranking "hot" como proxy de
    engajamento (o Reddit já ordena essa listagem por popularidade)."""
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for listing, ranked in (("", True), ("new/", False)):
        url = f"https://www.reddit.com/r/GTA6/{listing}.rss?limit=20"
        try:
            feed = feedparser.parse(url, agent=UA)
            if feed.get("status") != 200 or not feed.entries:
                raise ValueError(f"status={feed.get('status')}")
        except Exception as e:
            print(f"[reddit] falhou '{listing or 'hot'}': {e}", file=sys.stderr)
            continue
        for rank, entry in enumerate(feed.entries):
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                published = datetime.now(timezone.utc)
            if published < cutoff:
                continue
            items.append({
                "source": "reddit",
                "headline": entry.get("title", ""),
                "desc": _clean_reddit_summary(entry.get("summary", ""))[:280] or "Post em alta no r/GTA6 — ver fonte.",
                "url": entry.get("link", ""),
                "published": published,
                "engagement": max(0, 5000 - rank * 250) if ranked else 0,
                "keyword_bonus": 0,
            })
    return items


def _parse_iso8601_duration(text):
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", text or "")
    if not m:
        return 0
    h, mnt, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mnt * 60 + s


def load_channel_baselines():
    if not os.path.exists(CHANNEL_BASELINE_FILE):
        return {}
    try:
        with open(CHANNEL_BASELINE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[baseline] falhou ler {CHANNEL_BASELINE_FILE}, começando do zero: {e}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_channel_baselines(baselines):
    with open(CHANNEL_BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baselines, f, ensure_ascii=False, indent=2)


def fetch_channel_recent_views(channel_id, key):
    """Busca views dos últimos uploads de um canal. Retorna lista de ints
    (lista vazia se o canal não existir ou qualquer chamada falhar)."""
    if not channel_id:
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "contentDetails", "id": channel_id, "key": key},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return []
        uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"[baseline] falhou channels.list pra {channel_id}: {e}", file=sys.stderr)
        return []

    try:
        r2 = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": 15, "key": key},
            timeout=15,
        )
        r2.raise_for_status()
        video_ids = [it["contentDetails"]["videoId"] for it in r2.json().get("items", [])]
    except Exception as e:
        print(f"[baseline] falhou playlistItems pra {channel_id}: {e}", file=sys.stderr)
        return []

    if not video_ids:
        return []

    try:
        r3 = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": ",".join(video_ids), "key": key},
            timeout=15,
        )
        r3.raise_for_status()
        return [int(v.get("statistics", {}).get("viewCount", 0)) for v in r3.json().get("items", [])]
    except Exception as e:
        print(f"[baseline] falhou videos.list pra {channel_id}: {e}", file=sys.stderr)
        return []


def get_channel_baseline(channel_id, key, baselines):
    """Retorna (medianaViews, tamanhoAmostra). Usa cache se tiver menos de
    BASELINE_MAX_AGE_HOURS; senão recalcula e atualiza `baselines` in place.
    Retorna (None, amostra) se não houver amostra suficiente."""
    if not channel_id:
        return None, 0

    entry = baselines.get(channel_id)
    if entry:
        try:
            computed_at = datetime.fromisoformat(entry["calculadoEm"])
            age_hours = (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600
            if age_hours < BASELINE_MAX_AGE_HOURS:
                return entry.get("medianViews"), entry.get("amostra", 0)
        except Exception as e:
            # Corrupted, missing, or timezone-naive calculadoEm — treat as stale, recompute below
            print(f"[baseline] cache inválido pra {channel_id}: {e}", file=sys.stderr)

    views = fetch_channel_recent_views(channel_id, key)
    # Cacheia tanto sucesso quanto amostra insuficiente/falha, com o mesmo TTL de
    # 24h — evita rebuscar o mesmo canal pequeno/com falha a cada item, toda rodada.
    median_views = statistics.median(views) if len(views) >= BASELINE_MIN_SAMPLE else None
    baselines[channel_id] = {
        "medianViews": median_views,
        "amostra": len(views),
        "calculadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return median_views, len(views)


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
    durations = {}
    if video_ids:
        try:
            r2 = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics,contentDetails", "id": ",".join(video_ids), "key": key},
                timeout=15,
            )
            r2.raise_for_status()
            for v in r2.json().get("items", []):
                stats[v["id"]] = int(v.get("statistics", {}).get("viewCount", 0))
                durations[v["id"]] = _parse_iso8601_duration(v.get("contentDetails", {}).get("duration", ""))
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
        # Shorts oficialmente vão até 3 min (180s); abaixo disso classifica como "curto".
        video_type = "curto" if durations.get(vid, 9999) <= 180 else "longo"
        items.append({
            "source": "youtube",
            "videoType": video_type,
            "channelId": snippet.get("channelId"),
            "headline": snippet.get("title", ""),
            "desc": (snippet.get("description") or "")[:280] or f"Vídeo em alta sobre GTA 6 ({views} views).",
            "url": f"https://youtube.com/watch?v={vid}",
            "published": published,
            "engagement": views,
            "keyword_bonus": 0,
        })
    return items


def _rewrite_prompt(raw_items):
    prompt_items = [
        {"headline": it["headline"], "desc": it["desc"], "cat": it["cat"]}
        for it in raw_items
    ]
    return (
        "Você escreve pro canal de conteúdo 'Sem Missão', focado em GTA 6. "
        "Reescreva cada item abaixo em PT-BR, tom direto de criador, nada corporativo. "
        "Para cada item retorne: headline (uma frase chamativa), desc (1-2 frases factuais), "
        "hook (sugestão concreta de gancho pra abrir um vídeo curto sobre o assunto). "
        "Responda SÓ com JSON: lista de objetos com headline, desc, hook, na MESMA ORDEM da entrada, "
        "sem texto antes ou depois.\n\n"
        f"ITENS:\n{json.dumps(prompt_items, ensure_ascii=False, indent=2)}"
    )


def _parse_rewrite_response(text, expected_len):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    rewritten = json.loads(match.group(0)) if match else None
    if rewritten and len(rewritten) == expected_len:
        return rewritten
    return None


def maybe_rewrite_with_claude(raw_items):
    """Se ANTHROPIC_API_KEY existir, reescreve headline/desc/hook no tom do canal.
    Chave paga por uso (console.anthropic.com) — cada implantação deste repo usa a SUA
    própria chave, configurada como secret NO REPO de quem estiver rodando. Nunca é
    compartilhada entre implantações diferentes."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not raw_items:
        return None
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
                "messages": [{"role": "user", "content": _rewrite_prompt(raw_items)}],
            },
            timeout=60,
        )
        r.raise_for_status()
        return _parse_rewrite_response(r.json()["content"][0]["text"], len(raw_items))
    except Exception as e:
        print(f"[claude rewrite] falhou, usando fallback: {e}", file=sys.stderr)
    return None


def maybe_rewrite_with_gemini(raw_items):
    """Alternativa gratuita ao Claude: usa o free tier do Gemini (Google AI Studio) se
    GEMINI_API_KEY existir. Usa o alias "gemini-flash-latest" (não uma versão fixa como
    gemini-2.0-flash ou gemini-2.5-flash): contas novas do Google AI Studio ficam com cota
    zerada nos modelos antigos e alguns modelos fixos são descontinuados pra novos usuários
    (erro 404). O alias sempre aponta pro flash atual, que tem free tier ativo.
    Mesma regra do Claude: cada implantação usa a sua própria chave."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not raw_items:
        return None
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": _rewrite_prompt(raw_items)}]}]},
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_rewrite_response(text, len(raw_items))
    except Exception as e:
        print(f"[gemini rewrite] falhou, usando fallback: {e}", file=sys.stderr)
    return None


def compute_outliers(items, key, baselines, check_hot=True):
    """Marca item['outlier'] = True/False em cada item (in place). Cada item
    precisa ter as chaves 'url', 'engagement' (views), 'channelId', 'published'
    (datetime). Critério 1: entre os top HOT_TOP_N por views publicados nas
    últimas HOT_WINDOW_HOURS horas (só avaliado se check_hot=True — itens
    re-checados de rodadas anteriores nunca são elegíveis pra esse critério,
    só pra novos itens recém-buscados). Critério 2: views >= OUTLIER_CHANNEL_MULTIPLIER
    vezes a mediana do canal (se houver amostra suficiente)."""
    hot_urls = set()
    if check_hot:
        now = datetime.now(timezone.utc)
        hot_candidates = sorted(
            (it for it in items if (now - it["published"]).total_seconds() / 3600 <= HOT_WINDOW_HOURS),
            key=lambda it: it["engagement"],
            reverse=True,
        )[:HOT_TOP_N]
        hot_urls = {it["url"] for it in hot_candidates}

    for it in items:
        is_hot = it["url"] in hot_urls
        median_views, _sample = get_channel_baseline(it.get("channelId"), key, baselines)
        is_channel_outlier = bool(median_views) and it["engagement"] >= median_views * OUTLIER_CHANNEL_MULTIPLIER
        it["outlier"] = is_hot or is_channel_outlier


def _apply_language_safety(classified, rewritten):
    """Se a reescrita por IA não rodou com sucesso nessa rodada, uma notícia
    que não é originalmente em português ficaria exibida no idioma original
    — descarta em vez de mostrar errado (mesma filosofia do resumo diário:
    silêncio é preferível a exibir algo incorreto). newsLang é sempre um
    campo interno: nunca deve sobrar no item retornado."""
    if not rewritten:
        classified = [
            it for it in classified
            if not (it["source"] == "news" and it.get("newsLang") not in (None, "pt"))
        ]
    for it in classified:
        it.pop("newsLang", None)
    return classified


def build_items(existing_items, baselines):
    raw = fetch_news() + fetch_reddit() + fetch_youtube()
    raw.sort(key=lambda x: x["published"], reverse=True)

    seen_tokens = [normalize(it["headline"]) for it in existing_items]

    deduped = []
    for it in raw:
        if is_duplicate(it["headline"], seen_tokens):
            continue
        seen_tokens.append(normalize(it["headline"]))
        deduped.append(it)

    key = os.environ.get("YOUTUBE_API_KEY")
    youtube_deduped = [it for it in deduped if it["source"] == "youtube"]
    if youtube_deduped and key:
        compute_outliers(youtube_deduped, key, baselines)

    classified = []
    for it in deduped:
        cat = classify(it["headline"] + " " + it["desc"])
        if not cat:
            cat = "viral" if it["source"] in ("reddit", "youtube") else "curiosidade"
        recency_hours = (datetime.now(timezone.utc) - it["published"]).total_seconds() / 3600
        outlier = it.get("outlier", False)
        signal = score_item(recency_hours, it["engagement"], it["keyword_bonus"], outlier=outlier)
        classified.append({
            "cat": cat,
            "tagLabel": CAT_TAG_LABEL[cat],
            "source": it["source"],
            "videoType": it.get("videoType"),
            "channelId": it.get("channelId"),
            "outlier": outlier,
            "newsLang": it.get("newsLang"),
            "date": it["published"].strftime("%d/%m/%Y"),
            "publishedAt": it["published"].isoformat(timespec="seconds"),
            "headline": it["headline"].strip(),
            "desc": it["desc"].strip() or "Sem descrição disponível — ver fonte.",
            "signal": signal,
            "hook": HOOK_TEMPLATES[cat].format(headline=it["headline"].strip()),
            "url": it["url"],
        })

    # tenta melhorar texto: Claude primeiro (se configurado), senão Gemini grátis (se
    # configurado), senão fica no template mesmo — sem custo nenhum.
    rewritten = maybe_rewrite_with_claude(classified) or maybe_rewrite_with_gemini(classified)
    if rewritten:
        for orig, new in zip(classified, rewritten):
            orig["headline"] = new.get("headline", orig["headline"])
            orig["desc"] = new.get("desc", orig["desc"])
            orig["hook"] = new.get("hook", orig["hook"])

    classified = _apply_language_safety(classified, rewritten)

    return classified


def _extract_video_id(url):
    m = re.search(r"[?&]v=([\w-]+)", url or "")
    return m.group(1) if m else None


def recheck_youtube_items(existing_items, key, baselines):
    """Rebusca views/duração atuais dos itens source=='youtube' já salvos e
    recalcula videoType/outlier/signal com dado fresco. Se a chamada à API
    falhar inteira, não altera nada (itens ficam como estavam)."""
    yt_items = [it for it in existing_items if it.get("source") == "youtube"]
    if not yt_items or not key:
        return

    video_ids = [_extract_video_id(it["url"]) for it in yt_items]
    id_to_item = {vid: it for vid, it in zip(video_ids, yt_items) if vid}
    if not id_to_item:
        return

    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics,contentDetails", "id": ",".join(id_to_item.keys()), "key": key},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("items", [])
    except Exception as e:
        print(f"[youtube recheck] falhou, mantendo itens como estavam: {e}", file=sys.stderr)
        return

    fresh_stats = {}
    for v in results:
        views = int(v.get("statistics", {}).get("viewCount", 0))
        duration_s = _parse_iso8601_duration(v.get("contentDetails", {}).get("duration", ""))
        fresh_stats[v["id"]] = {
            "views": views,
            "videoType": "curto" if duration_s <= 180 else "longo",
        }

    outlier_inputs = []
    for vid, it in id_to_item.items():
        stats = fresh_stats.get(vid)
        if not stats:
            continue
        outlier_inputs.append({
            "url": it["url"],
            "engagement": stats["views"],
            "channelId": it.get("channelId"),
            "published": datetime.fromisoformat(it["publishedAt"]),
        })
    compute_outliers(outlier_inputs, key, baselines, check_hot=False)
    outlier_by_url = {oi["url"]: oi["outlier"] for oi in outlier_inputs}

    for vid, it in id_to_item.items():
        stats = fresh_stats.get(vid)
        if not stats:
            continue
        it["videoType"] = stats["videoType"]
        it["outlier"] = outlier_by_url.get(it["url"], False)
        recency_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(it["publishedAt"])).total_seconds() / 3600
        it["signal"] = score_item(recency_hours, stats["views"], 0, outlier=it["outlier"])


def _trim_with_quotas(combined, max_items):
    """Protege por categoria de alto sinal (comportamento já existente) E por
    cota mínima de tipo de conteúdo (notícias, vídeo longo, vídeo curto) — sem
    a cota de tipo, o engajamento sintético do Reddit expulsa sistematicamente
    notícias e vídeos do corte, porque eles nunca têm engagement tão alto.
    Nunca força a existir mais itens de um tipo do que realmente há
    candidatos disponíveis. Reddit não tem cota fixa — preenche o restante do
    espaço naturalmente."""
    if len(combined) <= max_items:
        return combined

    def _top_n(predicate, n):
        matching = sorted((it for it in combined if predicate(it)), key=lambda x: x["signal"], reverse=True)
        return matching[:n]

    cat_protected = [it for it in combined if it["cat"] in ("lancamento", "trabalhista", "vendas") and it["signal"] >= 5]
    news_protected = _top_n(lambda it: it.get("source") == "news", MIN_NEWS)
    longo_protected = _top_n(lambda it: it.get("source") == "youtube" and it.get("videoType") == "longo", MIN_VIDEO_LONGO)
    curto_protected = _top_n(lambda it: it.get("source") == "youtube" and it.get("videoType") == "curto", MIN_VIDEO_CURTO)

    protected = []
    seen_urls = set()
    # Ordem importa: as cotas de tipo (news/longo/curto) entram primeiro, e a
    # proteção de categoria (sem limite de tamanho) entra por último. Cada
    # cota de tipo é limitada a 10 itens (no máximo 30 no total, bem abaixo de
    # MAX_ITEMS), enquanto cat_protected pode crescer sem limite. Como o corte
    # final é (protected + rest)[:max_items], se o conjunto protegido
    # combinado ultrapassar max_items, é a proteção de categoria (não
    # limitada) que deve ser truncada — nunca as cotas de tipo garantidas.
    for group in (news_protected, longo_protected, curto_protected, cat_protected):
        for it in group:
            url = it.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            protected.append(it)

    rest = [it for it in combined if it.get("url") not in seen_urls]
    rest.sort(key=lambda x: x["signal"], reverse=True)
    return (protected + rest)[:max_items]


def main():
    existing = load_existing()
    existing_items = existing.get("items", [])
    baselines = load_channel_baselines()

    key = os.environ.get("YOUTUBE_API_KEY")
    if key:
        recheck_youtube_items(existing_items, key, baselines)

    new_items = build_items(existing_items, baselines)
    save_channel_baselines(baselines)

    combined = new_items + existing_items
    combined = _trim_with_quotas(combined, MAX_ITEMS)

    out = {
        "updated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "items": combined,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"OK — {len(new_items)} itens novos, {len(combined)} no total.")


if __name__ == "__main__":
    main()
