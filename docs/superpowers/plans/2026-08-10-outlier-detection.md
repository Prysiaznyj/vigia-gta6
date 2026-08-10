# Detecção de vídeo outlier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Marcar vídeos do YouTube como "outlier" (visualização muito acima do normal, seja por estar bombando agora ou por estar muito acima do padrão do próprio canal) no VIGIA GTA VI, validando tudo num repositório de teste isolado antes de tocar em produção.

**Architecture:** `scripts/fetch_signals.py` ganha um cache local (`channel_baselines.json`) com a mediana de views recentes de cada canal, uma função que classifica outlier por dois critérios independentes, e um passo novo em `main()` que re-busca views atuais dos vídeos do YouTube já salvos a cada rodada (não só dos novos). `index.html` ganha um selo visual e uma opção de filtro. Tudo isso é implementado e testado num repositório GitHub novo (`vigia-gta6-test`), não no repositório de produção (`vigia-gta6`).

**Tech Stack:** Python 3.11 (runtime do GitHub Actions) / 3.13 (ambiente local de teste manual) — sem dependências novas, `statistics` é da stdlib. HTML/CSS/JS puro no front-end (sem framework, mesmo padrão do arquivo atual).

## Global Constraints

- Spec de referência: `docs/superpowers/specs/2026-08-10-outlier-detection-design.md`.
- Todo o trabalho de código acontece em `D:\Clientes\8 - GTA VI\NOSSO APP\vigia-gta6-test` (repositório de teste, criado na Task 1) — **nunca** commitar/pushar direto na pasta/repositório de produção (`vigia-gta6-site` / `Prysiaznyj/vigia-gta6`) durante este plano.
- Sem dependência nova em `requirements.txt` (feedparser==6.0.11, requests==2.32.3 já cobrem tudo — `statistics` é módulo padrão do Python).
- Sem suite de teste formal (decisão da spec) — verificação manual via scripts `python -c` isolados, seguindo o mesmo padrão já usado no projeto (ver histórico de `scripts/fetch_signals.py`).
- Constantes da regra de outlier (definidas na spec, não mude sem confirmar com o usuário): `HOT_WINDOW_HOURS=4`, `HOT_TOP_N=6`, `BASELINE_MAX_AGE_HOURS=24`, `BASELINE_MIN_SAMPLE=3`, `OUTLIER_CHANNEL_MULTIPLIER=2`.
- Nunca escrever valores reais de chave de API (`YOUTUBE_API_KEY`, `GEMINI_API_KEY`) dentro de nenhum arquivo commitado — só como variável de ambiente na hora de rodar comandos, ou via `gh secret set`.
- Python local pra verificação manual: `/c/Python313/python.exe` (ambiente Git Bash já configurado).

---

### Task 1: Criar repositório de teste isolado

**Files:**
- Create: `D:\Clientes\8 - GTA VI\NOSSO APP\vigia-gta6-test\` (cópia completa de `vigia-gta6-site`, sem a pasta `.git`)

**Interfaces:**
- Produces: repositório GitHub público `Prysiaznyj/vigia-gta6-test`, com Pages ativo e secrets `YOUTUBE_API_KEY` e `GEMINI_API_KEY` configurados. Todas as tasks seguintes operam dentro dessa pasta.

- [ ] **Step 1: Copiar os arquivos do projeto (sem histórico git)**

```bash
mkdir -p "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
rsync -a --exclude='.git' "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-site/" "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/"
ls -la "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
```

Expected: lista os mesmos arquivos de `vigia-gta6-site` (`index.html`, `data.json`, `setup.sh`, `scripts/`, `.github/`, `docs/`, etc.), sem pasta `.git`.

- [ ] **Step 2: Rodar o setup.sh no diretório novo, com as chaves já conhecidas como variável de ambiente**

As chaves `YOUTUBE_API_KEY` e `GEMINI_API_KEY` já foram validadas e configuradas no repositório de produção anteriormente nesta sessão — reusar os mesmos valores aqui, exportando-os no shell (nunca escrevê-los num arquivo).

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
export YOUTUBE_API_KEY="<valor já usado no secret de produção>"
export GEMINI_API_KEY="<valor já usado no secret de produção>"
./setup.sh vigia-gta6-test public
```

Expected: saída termina em algo como `Feito. Site (...): https://Prysiaznyj.github.io/vigia-gta6-test/`, sem erro.

- [ ] **Step 3: Verificar que o repositório, Pages e secrets ficaram corretos**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh repo view Prysiaznyj/vigia-gta6-test --json name,visibility,url
gh secret list --repo Prysiaznyj/vigia-gta6-test
```

Expected: `visibility: PUBLIC`, e a listagem de secrets mostra `YOUTUBE_API_KEY` e `GEMINI_API_KEY`.

- [ ] **Step 4: Commit inicial já foi feito pelo setup.sh — confirmar**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git log --oneline
git remote -v
```

Expected: 1 commit (`vigia gta6: setup inicial`), remote `origin` apontando pra `https://github.com/Prysiaznyj/vigia-gta6-test.git`.

---

### Task 2: Capturar channelId no fetch_youtube e preparar score_item pro bônus de outlier

**Files:**
- Modify: `scripts/fetch_signals.py:100` (`score_item`)
- Modify: `scripts/fetch_signals.py:195-262` (`fetch_youtube`)
- Modify: `scripts/fetch_signals.py:13-28` (imports/constantes)

**Interfaces:**
- Produces: `score_item(recency_hours, engagement, keyword_bonus, outlier=False) -> int` (1-5). Itens de `fetch_youtube()` ganham a chave `"channelId": str|None`.

- [ ] **Step 1: Adicionar import de `statistics` e as constantes novas**

Em `scripts/fetch_signals.py`, logo depois da linha 22 (`import requests`), adicionar:

```python
import statistics
```

E depois da linha 28 (`UA = ...`), adicionar:

```python
CHANNEL_BASELINE_FILE = os.path.join(os.path.dirname(__file__), "..", "channel_baselines.json")
CHANNEL_BASELINE_FILE = os.path.abspath(CHANNEL_BASELINE_FILE)
HOT_WINDOW_HOURS = 4
HOT_TOP_N = 6
BASELINE_MAX_AGE_HOURS = 24
BASELINE_MIN_SAMPLE = 3
OUTLIER_CHANNEL_MULTIPLIER = 2
```

- [ ] **Step 2: Adicionar o bônus de outlier em `score_item`**

Substituir (linha 100-111):

```python
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
```

por:

```python
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
```

- [ ] **Step 3: Verificar manualmente que a assinatura antiga ainda funciona (compatibilidade) e o bônus funciona**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
from fetch_signals import score_item
print(score_item(2, 100, 0))
print(score_item(2, 100, 0, outlier=True))
"
```

Expected: primeira linha `3`, segunda linha `5` (3 + 2, capado em 5).

- [ ] **Step 4: Adicionar `channelId` ao item retornado por `fetch_youtube`**

Em `fetch_youtube` (linha 252-261), substituir:

```python
        items.append({
            "source": "youtube",
            "videoType": video_type,
            "headline": snippet.get("title", ""),
            "desc": (snippet.get("description") or "")[:280] or f"Vídeo em alta sobre GTA 6 ({views} views).",
            "url": f"https://youtube.com/watch?v={vid}",
            "published": published,
            "engagement": views,
            "keyword_bonus": 0,
        })
```

por:

```python
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
```

- [ ] **Step 5: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona constantes de outlier, bônus em score_item e captura de channelId"
```

---

### Task 3: Cache de baseline por canal

**Files:**
- Modify: `scripts/fetch_signals.py` (adicionar funções novas logo antes de `fetch_youtube`, após a linha de `_parse_iso8601_duration` — linha 192 no arquivo atual, o número exato pode ter mudado após a Task 2, procurar pelo `def fetch_youtube():`)

**Interfaces:**
- Consumes: `CHANNEL_BASELINE_FILE`, `BASELINE_MAX_AGE_HOURS`, `BASELINE_MIN_SAMPLE` (Task 2).
- Produces: `load_channel_baselines() -> dict`, `save_channel_baselines(baselines: dict) -> None`, `fetch_channel_recent_views(channel_id: str, key: str) -> list[int]`, `get_channel_baseline(channel_id: str|None, key: str, baselines: dict) -> tuple[float|None, int]` (median, sample_size).

- [ ] **Step 1: Escrever as funções de cache, logo antes de `def fetch_youtube():`**

```python
def load_channel_baselines():
    if not os.path.exists(CHANNEL_BASELINE_FILE):
        return {}
    with open(CHANNEL_BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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
        computed_at = datetime.fromisoformat(entry["calculadoEm"])
        age_hours = (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600
        if age_hours < BASELINE_MAX_AGE_HOURS:
            return entry.get("medianViews"), entry.get("amostra", 0)

    views = fetch_channel_recent_views(channel_id, key)
    if len(views) < BASELINE_MIN_SAMPLE:
        return None, len(views)

    median_views = statistics.median(views)
    baselines[channel_id] = {
        "medianViews": median_views,
        "amostra": len(views),
        "calculadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return median_views, len(views)
```

- [ ] **Step 2: Verificar sintaxe**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
```

Expected: `compila OK`.

- [ ] **Step 3: Verificar manualmente o cache com dados fake (sem bater na API de verdade)**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
from datetime import datetime, timezone, timedelta
import fetch_signals as fs

baselines = {
    'CANAL_FRESCO': {
        'medianViews': 1000,
        'amostra': 5,
        'calculadoEm': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    },
    'CANAL_VELHO': {
        'medianViews': 500,
        'amostra': 5,
        'calculadoEm': (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec='seconds'),
    },
}

# cache fresco: deve retornar sem chamar a API (chave inválida não importa aqui)
median, sample = fs.get_channel_baseline('CANAL_FRESCO', 'chave-invalida-nao-usada', baselines)
print('cache fresco ->', median, sample)
assert median == 1000 and sample == 5

# cache velho: vai tentar recalcular (com chave inválida, API falha, retorna amostra insuficiente)
median2, sample2 = fs.get_channel_baseline('CANAL_VELHO', 'chave-invalida', baselines)
print('cache velho (recalcula, falha graciosamente) ->', median2, sample2)
assert median2 is None

# sem channelId
median3, sample3 = fs.get_channel_baseline(None, 'chave-invalida', baselines)
print('sem channelId ->', median3, sample3)
assert median3 is None and sample3 == 0

print('OK')
"
```

Expected: imprime as três linhas e termina em `OK`, sem exception.

- [ ] **Step 4: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona cache de baseline de canal (mediana de views recentes)"
```

---

### Task 4: Função compute_outliers e integração em build_items

**Files:**
- Modify: `scripts/fetch_signals.py` (nova função antes de `build_items`; modificar `build_items`, linha 344-388 no estado pré-Task-2/3 — localizar por `def build_items():`)

**Interfaces:**
- Consumes: `get_channel_baseline` (Task 3), `score_item(..., outlier=...)` (Task 2).
- Produces: `compute_outliers(items: list[dict], key: str, baselines: dict) -> None` (muta `item["outlier"]` in place; cada item precisa ter `"url"`, `"engagement"`, `"channelId"`, `"published"`). `build_items(existing_items: list[dict], baselines: dict) -> list[dict]` (nova assinatura — não lê mais `load_existing()` internamente).

- [ ] **Step 1: Escrever `compute_outliers`, logo antes de `def build_items():`**

```python
def compute_outliers(items, key, baselines):
    """Marca item['outlier'] = True/False em cada item (in place). Cada item
    precisa ter as chaves 'url', 'engagement' (views), 'channelId', 'published'
    (datetime). Critério 1: entre os top HOT_TOP_N por views publicados nas
    últimas HOT_WINDOW_HOURS horas. Critério 2: views >= OUTLIER_CHANNEL_MULTIPLIER
    vezes a mediana do canal (se houver amostra suficiente)."""
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
```

- [ ] **Step 2: Verificar manualmente com dados fake**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
from datetime import datetime, timezone, timedelta
import fetch_signals as fs

now = datetime.now(timezone.utc)
items = [
    {'url': 'v1', 'engagement': 100000, 'channelId': None, 'published': now - timedelta(hours=1)},  # deve ser hot
    {'url': 'v2', 'engagement': 10, 'channelId': None, 'published': now - timedelta(hours=1)},       # não hot (perde no top 6 se houver mais de 6 candidatos)
    {'url': 'v3', 'engagement': 500, 'channelId': None, 'published': now - timedelta(hours=10)},     # fora da janela de 4h
]
baselines = {}
fs.compute_outliers(items, 'chave-nao-importa-sem-channelId', baselines)
for it in items:
    print(it['url'], it['outlier'])
assert items[0]['outlier'] is True
assert items[2]['outlier'] is False
print('OK')
"
```

Expected: imprime `v1 True`, `v2 True` (só 2 candidatos na janela de 4h, top 6 pega os dois), `v3 False`, termina em `OK`.

- [ ] **Step 3: Reescrever `build_items` pra receber `existing_items`/`baselines` e chamar `compute_outliers`**

Substituir o corpo completo da função (do `def build_items():` até o `return classified`, incluindo as linhas de rewrite) por:

```python
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

    return classified
```

Note: `main()` ainda chama `build_items()` sem argumentos neste ponto — isso quebra até a Task 5 atualizar `main()`. Tudo bem, a Task 5 é a próxima e conserta isso; não rodar `main()` real entre as duas tasks.

- [ ] **Step 4: Verificar sintaxe**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
```

- [ ] **Step 5: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona compute_outliers e integra no build_items (nova assinatura)"
```

---

### Task 5: Recheck de itens existentes do YouTube e reestruturação do main()

**Files:**
- Modify: `scripts/fetch_signals.py` (nova função `_extract_video_id` e `recheck_youtube_items`, antes de `def main():`; reescrever `main()`, linha 391-408+ no estado original)

**Interfaces:**
- Consumes: `compute_outliers`, `get_channel_baseline`, `_parse_iso8601_duration`, `score_item`, `load_channel_baselines`, `save_channel_baselines`, `build_items(existing_items, baselines)` (tasks anteriores).
- Produces: `_extract_video_id(url: str) -> str|None`. `recheck_youtube_items(existing_items: list[dict], key: str, baselines: dict) -> None` (muta os itens de `source == "youtube"` em `existing_items` in place: `videoType`, `outlier`, `signal`).

- [ ] **Step 1: Escrever `_extract_video_id` e `recheck_youtube_items`, logo antes de `def main():`**

```python
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
    compute_outliers(outlier_inputs, key, baselines)
    outlier_by_url = {oi["url"]: oi["outlier"] for oi in outlier_inputs}

    for vid, it in id_to_item.items():
        stats = fresh_stats.get(vid)
        if not stats:
            continue
        it["videoType"] = stats["videoType"]
        it["outlier"] = outlier_by_url.get(it["url"], False)
        recency_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(it["publishedAt"])).total_seconds() / 3600
        it["signal"] = score_item(recency_hours, stats["views"], 0, outlier=it["outlier"])
```

- [ ] **Step 2: Reescrever `main()` inteiro**

```python
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
```

(Mantém a linha `if __name__ == "__main__": main()` que já existia no fim do arquivo — não duplicar.)

- [ ] **Step 3: Verificar sintaxe**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
```

- [ ] **Step 4: Verificar manualmente `recheck_youtube_items` com um item fake e API real (usa a YOUTUBE_API_KEY do ambiente)**

```bash
export YOUTUBE_API_KEY="<mesmo valor usado na Task 1>"
/c/Python313/python.exe -c "
import sys, os
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
from datetime import datetime, timezone, timedelta
import fetch_signals as fs

existing = [{
    'source': 'youtube',
    'url': 'https://youtube.com/watch?v=dQw4w9WgXcQ',
    'channelId': None,
    'publishedAt': (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec='seconds'),
    'videoType': 'longo',
    'outlier': False,
    'signal': 1,
}]
baselines = {}
fs.recheck_youtube_items(existing, os.environ['YOUTUBE_API_KEY'], baselines)
print(existing[0])
assert existing[0]['signal'] >= 1
print('OK')
"
```

Expected: imprime o dict do item com `videoType`, `outlier` e `signal` atualizados (o vídeo é o "Never Gonna Give You Up", tem visualizações na casa dos bilhões — `videoType` deve sair `longo`), termina em `OK`.

- [ ] **Step 5: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona recheck de views do YouTube em itens já rastreados; reestrutura main()"
```

---

### Task 6: Atualizar workflow pra commitar channel_baselines.json

**Files:**
- Modify: `.github/workflows/sweep.yml`

**Interfaces:**
- Nenhuma (mudança de configuração).

- [ ] **Step 1: Atualizar o passo de commit**

Em `.github/workflows/sweep.yml`, no passo "Commitar data.json se mudou", trocar:

```yaml
          git add data.json
```

por:

```yaml
          git add data.json channel_baselines.json
```

- [ ] **Step 2: Verificar o arquivo yaml é válido**

```bash
/c/Python313/python.exe -c "
import yaml
yaml.safe_load(open('D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/.github/workflows/sweep.yml', encoding='utf-8'))
print('YAML válido')
" 2>&1 || /c/Python313/python.exe -m pip install --quiet pyyaml && /c/Python313/python.exe -c "
import yaml
yaml.safe_load(open('D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/.github/workflows/sweep.yml', encoding='utf-8'))
print('YAML válido')
"
```

Expected: `YAML válido`.

- [ ] **Step 3: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add .github/workflows/sweep.yml
git commit -m "Workflow também commita channel_baselines.json"
```

---

### Task 7: Selo visual de outlier e filtro no dropdown

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: campo `outlier: true|false` nos itens de `data.json` (Task 4/5).

- [ ] **Step 1: Adicionar CSS do selo**

Logo depois do bloco `.tag.viral{color:#b98bff;}` (dentro de `<style>`), adicionar:

```css
  .outlier-badge{
    display:inline-block;
    font-family:'JetBrains Mono', monospace;
    font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;
    padding:3px 8px; margin-left:8px;
    background:linear-gradient(90deg, var(--pink), var(--gold));
    color:#0a0518;
  }
```

- [ ] **Step 2: Adicionar a opção no dropdown**

No `<select id="sortMode">`, depois de `<option value="video_curto">Vídeos curtos (shorts)</option>`, adicionar:

```html
      <option value="outliers">Outliers 🔥</option>
```

- [ ] **Step 3: Adicionar o filtro no JS**

No objeto `SOURCE_FILTERS`, adicionar a chave:

```javascript
  outliers: d => d.outlier === true,
```

(Fica junto das outras chaves `noticias`, `reddit`, `video`, `video_longo`, `video_curto`.)

- [ ] **Step 4: Renderizar o selo no card**

Na função `cardHTML(d)`, adicionar antes do `return`:

```javascript
  const outlierBadge = d.outlier ? '<span class="outlier-badge">OUTLIER 🔥</span>' : '';
```

E no template, trocar:

```html
        <span class="tag ${meta.class}">${meta.label}</span>
```

por:

```html
        <span class="tag ${meta.class}">${meta.label}</span>${outlierBadge}
```

- [ ] **Step 5: Verificar visualmente com dados fake locais**

```bash
SCRATCH="C:/Users/lucas/AppData/Local/Temp/claude/C--Users-lucas/450e1f14-02cb-4b1f-a0f0-f3338a4c807d/scratchpad"
mkdir -p "$SCRATCH/outlier_preview"
cp "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/index.html" "$SCRATCH/outlier_preview/index.html"
cat > "$SCRATCH/outlier_preview/data.json" << 'EOF'
{
  "updated": "2026-08-10T12:00:00+00:00",
  "items": [
    {"cat":"viral","tagLabel":"Viral","source":"youtube","videoType":"curto","outlier":true,"date":"10/08/2026","publishedAt":"2026-08-10T11:00:00+00:00","headline":"Vídeo bombando agora","desc":"Teste outlier.","signal":5,"hook":"x","url":"#"},
    {"cat":"viral","tagLabel":"Viral","source":"youtube","videoType":"longo","outlier":false,"date":"10/08/2026","publishedAt":"2026-08-10T09:00:00+00:00","headline":"Vídeo normal","desc":"Sem outlier.","signal":2,"hook":"x","url":"#"}
  ]
}
EOF
cd "$SCRATCH/outlier_preview"
/c/Python313/python.exe -m http.server 8792 --bind 127.0.0.1
```

Rodar em background, abrir `http://127.0.0.1:8792` no Browser pane (via `preview_start`), conferir visualmente que o primeiro card mostra o selo "OUTLIER 🔥" ao lado da tag, o segundo não. Testar a opção "Outliers 🔥" no dropdown e confirmar que só o primeiro card aparece. Depois, encerrar o servidor e apagar `$SCRATCH/outlier_preview`.

- [ ] **Step 6: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add index.html
git commit -m "Adiciona selo visual e filtro de outlier no site"
```

---

### Task 8: Validação end-to-end no repositório de teste

**Files:** nenhum (só execução/verificação)

**Interfaces:** nenhuma nova — valida o comportamento de ponta a ponta de todas as tasks anteriores.

- [ ] **Step 1: Push de tudo pro repositório de teste**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git push
```

- [ ] **Step 2: Disparar o workflow manualmente**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh workflow run sweep.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar ~1 minuto, depois:

```bash
gh run list --repo Prysiaznyj/vigia-gta6-test --limit 1
```

Pegar o `run id` da saída e:

```bash
gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --log 2>&1 | grep -iE "outlier|baseline|reddit|youtube|OK —"
```

Expected: status final `success`, linha `OK — N itens novos, M no total.`, sem stack trace não tratado.

- [ ] **Step 3: Conferir o data.json e channel_baselines.json resultantes**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh api repos/Prysiaznyj/vigia-gta6-test/contents/data.json --jq '.content' | base64 -d > /tmp/test_data.json
/c/Python313/python.exe -c "
import json
d = json.load(open('/tmp/test_data.json', encoding='utf-8'))
yt = [it for it in d['items'] if it.get('source') == 'youtube']
print('itens youtube:', len(yt))
print('outliers:', sum(1 for it in yt if it.get('outlier')))
for it in yt[:5]:
    print(it['outlier'], it['videoType'], it['headline'][:60])
"
gh api repos/Prysiaznyj/vigia-gta6-test/contents/channel_baselines.json --jq '.content' 2>&1 | base64 -d 2>/dev/null | head -c 500 || echo "channel_baselines.json ainda não existe (ok se nenhum canal teve amostra suficiente ainda)"
```

Expected: alguns itens de YouTube com `outlier: true/false` variando (não todos iguais), `videoType` presente. `channel_baselines.json` existe ou a mensagem de "ainda não existe" aparece sem erro.

- [ ] **Step 4: Rodar de novo pra confirmar que o recheck funciona (não crasha na segunda rodada)**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh workflow run sweep.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar ~1 minuto, checar status `success` de novo (mesmo padrão do Step 2).

- [ ] **Step 5: Conferir visualmente o site publicado**

Abrir `https://Prysiaznyj.github.io/vigia-gta6-test/` (Browser pane), confirmar que o site carrega, os filtros funcionam, e (se algum vídeo tiver sido marcado outlier) o selo aparece.

- [ ] **Step 6: Reportar resultado ao usuário e aguardar aprovação antes de portar pra produção**

Não fazer merge/port pro repositório `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` nesta task — isso é uma decisão explícita do usuário, fora do escopo deste plano.
