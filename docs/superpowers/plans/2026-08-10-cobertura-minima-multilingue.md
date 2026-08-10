# Cobertura mínima + notícias multilíngues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantir que cada tipo de conteúdo (notícias, vídeo longo, vídeo curto) tenha uma cota mínima protegida no corte de itens do VIGIA GTA VI, elevar o total mantido, e ampliar a busca de notícias pra português/inglês/espanhol — sem nunca exibir conteúdo fora do português no site.

**Architecture:** Três mudanças independentes em `scripts/fetch_signals.py`: (1) uma função de corte nova (`_trim_with_quotas`) que protege cotas mínimas por tipo de conteúdo além da proteção por categoria já existente; (2) `fetch_news()` reescrita pra buscar em 3 locales do Google News RSS; (3) uma função de segurança de idioma (`_apply_language_safety`) que descarta notícia não-portuguesa se a reescrita por IA não rodou naquela rodada.

**Tech Stack:** Python 3.11/3.13, sem dependência nova.

## Global Constraints

- Spec de referência: `docs/superpowers/specs/2026-08-10-cobertura-minima-multilingue-design.md`.
- Todo o trabalho acontece em `D:\Clientes\8 - GTA VI\NOSSO APP\vigia-gta6-test` (repositório de teste já existente) — nunca commitar/pushar direto em `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` durante este plano.
- Valores exatos (não mudar sem confirmar com o usuário): `MAX_ITEMS = 60`, `MIN_NEWS = 10`, `MIN_VIDEO_LONGO = 10`, `MIN_VIDEO_CURTO = 10`. Reddit sem cota fixa.
- Locales de notícia: português (`pt-BR`/`BR`/`BR:pt-419`), inglês (`en-US`/`US`/`US:en`), espanhol (`es-419`/`MX`/`MX:es-419`).
- `newsLang` é um campo **interno**, usado só durante o processamento — nunca deve aparecer no `data.json` final escrito em disco, pra nenhum item (nem notícia, nem outros tipos).
- Regra de segurança de idioma: se a reescrita por IA (`maybe_rewrite_with_claude`/`maybe_rewrite_with_gemini`) não rodar com sucesso na rodada, todo item de notícia com `newsLang` diferente de `"pt"` (e diferente de ausente/`None`, que cobre itens de outras fontes) é removido do resultado daquela rodada.
- Sem dependência nova, sem suite de teste formal (verificação manual via `python -c`, mesmo padrão do projeto). Python local: `/c/Python313/python.exe`.

---

### Task 1: Corte com cota mínima por tipo de conteúdo

**Files:**
- Modify: `scripts/fetch_signals.py:27` (constante `MAX_ITEMS`)
- Modify: `scripts/fetch_signals.py` (adicionar `MIN_NEWS`/`MIN_VIDEO_LONGO`/`MIN_VIDEO_CURTO` junto das constantes existentes, perto de `OUTLIER_CHANNEL_MULTIPLIER`)
- Modify: `scripts/fetch_signals.py` (nova função `_trim_with_quotas`, logo antes de `def main():`)
- Modify: `scripts/fetch_signals.py` (corpo de `main()`, trocar o bloco de corte atual pela chamada à função nova)

**Interfaces:**
- Produces: `_trim_with_quotas(combined: list[dict], max_items: int) -> list[dict]`. Cada item de `combined` precisa ter as chaves `cat`, `signal`, `source`, `url`; itens de YouTube também têm `videoType`.

- [ ] **Step 1: Atualizar `MAX_ITEMS` e adicionar as constantes de cota**

Em `scripts/fetch_signals.py`, trocar a linha 27:
```python
MAX_ITEMS = 40
```
por:
```python
MAX_ITEMS = 60
```

E, logo depois da linha `OUTLIER_CHANNEL_MULTIPLIER = 2` (perto do topo do arquivo, junto das outras constantes de outlier), adicionar:
```python
MIN_NEWS = 10
MIN_VIDEO_LONGO = 10
MIN_VIDEO_CURTO = 10
```

- [ ] **Step 2: Escrever `_trim_with_quotas`, logo antes de `def main():`**

```python
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
    for group in (cat_protected, news_protected, longo_protected, curto_protected):
        for it in group:
            url = it.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            protected.append(it)

    rest = [it for it in combined if it.get("url") not in seen_urls]
    rest.sort(key=lambda x: x["signal"], reverse=True)
    return (protected + rest)[:max_items]
```

- [ ] **Step 3: Trocar o bloco de corte em `main()` pela chamada à função nova**

Em `main()`, substituir:
```python
    combined = new_items + existing_items
    # nunca derruba itens de alto sinal em categorias-chave; corta o resto se passar do limite
    if len(combined) > MAX_ITEMS:
        protected = [it for it in combined if it["cat"] in ("lancamento", "trabalhista", "vendas") and it["signal"] >= 5]
        rest = [it for it in combined if it not in protected]
        rest.sort(key=lambda x: x["signal"], reverse=True)
        combined = protected + rest
        combined = combined[:MAX_ITEMS]
```
por:
```python
    combined = new_items + existing_items
    combined = _trim_with_quotas(combined, MAX_ITEMS)
```

- [ ] **Step 4: Verificar manualmente com dados sintéticos que espelham o desequilíbrio real (Reddit com sinal alto expulsando notícia/vídeo)**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import fetch_signals as fs

def make(n, source, video_type=None, signal=5, cat='viral'):
    return [
        {'cat': cat, 'signal': signal - (i % 5), 'source': source, 'videoType': video_type, 'url': f'{source}-{video_type}-{i}'}
        for i in range(n)
    ]

news = make(15, 'news', signal=5)       # sinal varia 1-5, só 10 devem sobreviver
longo = make(12, 'youtube', 'longo', signal=5)
curto = make(12, 'youtube', 'curto', signal=5)
reddit = make(60, 'reddit', signal=5)   # todos sinal 5 — dominariam sem a cota

combined = news + longo + curto + reddit
assert len(combined) == 99

result = fs._trim_with_quotas(combined, 60)
assert len(result) == 60, f'esperado 60, veio {len(result)}'

from collections import Counter
def kind(it):
    if it['source'] == 'youtube':
        return f\"youtube-{it['videoType']}\"
    return it['source']
counts = Counter(kind(it) for it in result)
print(counts)
assert counts['news'] == 10, counts
assert counts['youtube-longo'] == 10, counts
assert counts['youtube-curto'] == 10, counts
assert counts['reddit'] == 30, counts
print('OK — cotas protegidas mesmo com Reddit tendo sinal máximo em todos os itens')
"
```

Expected: imprime o `Counter` com `news: 10, youtube-longo: 10, youtube-curto: 10, reddit: 30`, termina em `OK — cotas protegidas...`.

- [ ] **Step 5: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona corte com cota mínima protegida por tipo de conteúdo (notícia/vídeo longo/vídeo curto)"
```

---

### Task 2: Notícias em português, inglês e espanhol

**Files:**
- Modify: `scripts/fetch_signals.py:38-45` (substituir `NEWS_QUERIES` por `NEWS_LOCALES`)
- Modify: `scripts/fetch_signals.py:131-158` (reescrever `fetch_news()`)

**Interfaces:**
- Produces: `fetch_news() -> list[dict]` (mesma assinatura de antes; cada item agora também tem a chave `"newsLang": "pt"|"en"|"es"`).

- [ ] **Step 1: Substituir a constante `NEWS_QUERIES` por `NEWS_LOCALES`**

Trocar (linhas 38-45 no estado atual, localizar por `NEWS_QUERIES = [`):
```python
NEWS_QUERIES = [
    "GTA 6",
    "GTA VI Rockstar",
    "GTA 6 leak OR rumor",
    "GTA 6 Take-Two",
    "Rockstar Games union OR crunch",
    "GTA 6 preço OR price OR sales",
]
```
por:
```python
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
```

- [ ] **Step 2: Reescrever `fetch_news()` pra iterar sobre os 3 locales**

Substituir a função inteira (localizar por `def fetch_news():`):
```python
def fetch_news():
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for lang, hl, gl, ceid, queries in NEWS_LOCALES:
        for q in queries:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl={hl}&gl={gl}&ceid={ceid}"
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                print(f"[news] falhou '{q}' ({lang}): {e}", file=sys.stderr)
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
                    "newsLang": lang,
                    "headline": title,
                    "desc": getattr(entry, "summary", "")[:280],
                    "url": entry.link,
                    "published": published,
                    "engagement": 0,
                    "keyword_bonus": 1 if re.search(r"confirm|official|oficial", title.lower()) else 0,
                })
    return items
```

- [ ] **Step 3: Verificar manualmente contra o Google News real (sem chave de API necessária — é RSS público)**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import fetch_signals as fs

items = fs.fetch_news()
print('total:', len(items))
from collections import Counter
langs = Counter(it['newsLang'] for it in items)
print('por idioma:', langs)
assert all(it['newsLang'] in ('pt', 'en', 'es') for it in items), 'newsLang com valor inesperado'
assert all('newsLang' in it for it in items), 'item sem newsLang'
for it in items[:5]:
    print(it['newsLang'], '|', it['headline'][:70])
print('OK')
"
```

Expected: imprime o total e a contagem por idioma (varia conforme notícias reais do momento — não precisa ter exatamente os 3 idiomas representados nessa hora específica, mas não deve lançar exceção, e todo item deve ter `newsLang` em `pt`/`en`/`es`), termina em `OK`.

- [ ] **Step 4: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Amplia busca de notícias pra português, inglês e espanhol"
```

---

### Task 3: Segurança de idioma — nunca exibir notícia fora do português

**Files:**
- Modify: `scripts/fetch_signals.py` (`build_items()` — adicionar `newsLang` na construção de `classified`, nova função `_apply_language_safety`, trocar o final da função)

**Interfaces:**
- Consumes: `newsLang` nos itens brutos retornados por `fetch_news()` (Task 2).
- Produces: `_apply_language_safety(classified: list[dict], rewritten: list[dict]|None) -> list[dict]` (remove notícia não-portuguesa se `rewritten` for falso, e sempre remove a chave `newsLang` de todo item antes de retornar).

- [ ] **Step 1: Adicionar `newsLang` na construção do item classificado**

Em `build_items()`, no dicionário construído dentro do loop `for it in deduped:`, adicionar a chave `"newsLang"` (localizar por `"channelId": it.get("channelId"),`):
```python
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
```
(A única mudança é a linha `"newsLang": it.get("newsLang"),` inserida depois de `"outlier": outlier,`.)

- [ ] **Step 2: Escrever `_apply_language_safety`, logo antes de `def build_items(`**

```python
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
```

- [ ] **Step 3: Aplicar a função no fim de `build_items()`**

Substituir:
```python
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
por:
```python
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
```

- [ ] **Step 4: Verificar manualmente `_apply_language_safety` isoladamente, sem precisar de rede**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import fetch_signals as fs

items = [
    {'source': 'news', 'newsLang': 'pt', 'headline': 'noticia pt'},
    {'source': 'news', 'newsLang': 'en', 'headline': 'english news'},
    {'source': 'news', 'newsLang': 'es', 'headline': 'noticia es'},
    {'source': 'reddit', 'newsLang': None, 'headline': 'post reddit'},
    {'source': 'youtube', 'newsLang': None, 'headline': 'video'},
]

# sem reescrita (rewritten=None): descarta en/es, mantém pt/reddit/youtube
result_sem_ia = fs._apply_language_safety([dict(it) for it in items], None)
headlines = sorted(it['headline'] for it in result_sem_ia)
assert headlines == ['noticia pt', 'post reddit', 'video'], headlines
assert all('newsLang' not in it for it in result_sem_ia), 'newsLang vazou pro resultado'
print('sem IA -> OK:', headlines)

# com reescrita (rewritten truthy): mantém todos os 5
result_com_ia = fs._apply_language_safety([dict(it) for it in items], [{}]*5)
assert len(result_com_ia) == 5, result_com_ia
assert all('newsLang' not in it for it in result_com_ia), 'newsLang vazou pro resultado'
print('com IA -> OK: mantém os 5 itens, newsLang removido de todos')
print('TUDO OK')
"
```

Expected: imprime `sem IA -> OK: ['noticia pt', 'post reddit', 'video']`, depois `com IA -> OK: ...`, termina em `TUDO OK`.

- [ ] **Step 5: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py
git commit -m "Adiciona segurança de idioma: descarta notícia não-portuguesa se a reescrita por IA não rodar"
```

---

### Task 4: Validação end-to-end no repositório de teste

**Files:** nenhum (só execução/verificação).

**Interfaces:** nenhuma nova — valida o comportamento de ponta a ponta de todas as tasks anteriores, com o `data.json` real do repositório de teste.

- [ ] **Step 1: Push de tudo e disparo do workflow real**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git fetch origin
git rebase origin/main
git push
gh workflow run sweep.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar a conclusão (checar com `gh run list --repo Prysiaznyj/vigia-gta6-test --limit 1` e depois `gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --json status,conclusion` até `status` virar `completed`).

- [ ] **Step 2: Checar os logs em busca de erro**

```bash
gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --log 2>&1 | grep -iE "news|outlier|baseline|reddit|youtube|OK —|error|traceback|falhou"
```

Expected: status final `success`, linha `OK — N itens novos, M no total.`, sem traceback Python não tratado. Linhas `[news] falhou '...'` isoladas (uma query específica falhando) são aceitáveis — o requisito é não ter uma exceção que aborte a rodada inteira.

- [ ] **Step 3: Conferir a distribuição final no `data.json`**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
SCRATCH="C:/Users/lucas/AppData/Local/Temp/claude/C--Users-lucas/450e1f14-02cb-4b1f-a0f0-f3338a4c807d/scratchpad"
gh api repos/Prysiaznyj/vigia-gta6-test/contents/data.json --jq '.content' | base64 -d > "$SCRATCH/coverage_check.json"
/c/Python313/python.exe -c "
import json
from collections import Counter
d = json.load(open(r'C:\Users\lucas\AppData\Local\Temp\claude\C--Users-lucas\450e1f14-02cb-4b1f-a0f0-f3338a4c807d\scratchpad\coverage_check.json', encoding='utf-8'))
items = d['items']
print('total:', len(items))
assert len(items) <= 60, 'passou do MAX_ITEMS=60'
assert not any('newsLang' in it for it in items), 'newsLang vazou pro data.json final'
def kind(it):
    if it.get('source') == 'youtube':
        return f\"youtube-{it.get('videoType')}\"
    return it.get('source', 'SEM_SOURCE')
print(Counter(kind(it) for it in items))
"
rm -f "$SCRATCH/coverage_check.json"
```

Expected: `total` <= 60, nenhum item com a chave `newsLang` (confirma que o campo interno nunca vaza pro arquivo final), e a contagem por tipo mostra pelo menos alguma cobertura de `news` (não necessariamente exatamente 10 nessa primeira rodada, já que o pool ainda está se formando — o importante é não estar mais zerado como estava antes desta mudança).

- [ ] **Step 4: Checar visualmente o site publicado**

Abrir `https://prysiaznyj.github.io/vigia-gta6-test/` (Browser pane), testar o filtro "Notícias escritas" no dropdown e confirmar que aparece pelo menos algum item (diferente do estado anterior, que estava vazio).

- [ ] **Step 5: Reportar ao usuário e aguardar aprovação antes de portar pra produção**

Não fazer merge/port pro repositório `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` nesta task — decisão explícita do usuário, fora do escopo deste plano.
