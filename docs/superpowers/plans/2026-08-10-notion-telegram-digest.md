# Resumo diário (Notion + Telegram) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um script novo e independente que, 1x/dia, seleciona os sinais fortes das últimas 24h do `data.json` já existente, arquiva no Notion e empurra um resumo por Telegram — sem tocar em nada do que já funciona (coleta de sinais, site).

**Architecture:** `scripts/daily_digest.py` (novo, standalone, não importa `fetch_signals.py`) lê `data.json`, filtra por janela de 24h + `signal >= 4`, deduplica contra `digest_sent.json`, escreve no Notion via REST e manda uma mensagem HTML pro Telegram via Bot API. Workflow novo (`digest.yml`) roda isso 1x/dia via cron, separado do `sweep.yml`. `setup.sh` ganha um modo interativo opcional pra configurar as 4 credenciais novas.

**Tech Stack:** Python 3.11/3.13, só `requests` (já é dependência do projeto) — sem biblioteca nova.

## Global Constraints

- Spec de referência: `docs/superpowers/specs/2026-08-10-notion-telegram-digest-design.md`.
- Todo o trabalho acontece em `D:\Clientes\8 - GTA VI\NOSSO APP\vigia-gta6-test` (repositório de teste já existente, mantido vivo permanentemente pra esse tipo de teste) — **nunca** commitar/pushar direto em `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` durante este plano.
- `scripts/daily_digest.py` **não importa** `scripts/fetch_signals.py` — arquivo standalone, com seus próprios `DATA_FILE`/constantes.
- Critérios fixos da spec (não mudar sem confirmar com o usuário): janela de `LOOKBACK_HOURS = 24`, `MIN_SIGNAL = 4`, `MAX_ITEMS = 3`, retenção do `digest_sent.json` de `SENT_RETENTION_DAYS = 3`.
- Todas as 4 credenciais (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`) são opcionais — ausência de qualquer uma só pula aquele canal, nunca derruba o script.
- Sem dependência nova em `requirements.txt`.
- Sem suite de teste formal — verificação manual via `python -c`, mesmo padrão já usado no projeto. Python local: `/c/Python313/python.exe`.
- `digest_sent.json` marca um item como "enviado" assim que ele é **selecionado** pra rodada (independente de Notion/Telegram terem tido sucesso individualmente) — é só uma trava anti-duplicata pra janela de 24h sobreposta entre dias, não um mecanismo de retry. Documentar isso no docstring do `main()`.

---

### Task 1: Seleção e controle de itens já enviados

**Files:**
- Create: `scripts/daily_digest.py`

**Interfaces:**
- Produces: `load_items() -> list[dict]`, `load_sent() -> dict[str, str]`, `save_sent(sent: dict) -> None`, `prune_sent(sent: dict) -> dict`, `select_digest_items(items: list[dict], sent: dict) -> list[dict]`.

- [ ] **Step 1: Criar o arquivo com as constantes e as funções de carregar/seleção**

```python
#!/usr/bin/env python3
"""
VIGIA // GTA VI — resumo diário via Notion + Telegram.

Roda 1x/dia via GitHub Actions (cron). Lê o data.json já gerado pelo
fetch_signals.py (não importa nem modifica esse script), seleciona os
sinais fortes das últimas 24h e manda pro Notion (arquivo buscável) e
Telegram (empurrão pra pessoa agir no dia).

Todas as credenciais são opcionais — sem NOTION_TOKEN/NOTION_DATABASE_ID
pula o Notion, sem TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID pula o Telegram,
sem nenhuma das duas o script sai sem fazer nada.
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
    for it in items:
        published_at = it.get("publishedAt")
        if not published_at:
            continue
        try:
            published = datetime.fromisoformat(published_at)
        except Exception:
            continue
        if published < cutoff:
            continue
        if it.get("signal", 0) < MIN_SIGNAL:
            continue
        if it.get("url") in sent:
            continue
        candidates.append((published, it))
    candidates.sort(key=lambda pair: (pair[1]["signal"], pair[0]), reverse=True)
    return [it for _, it in candidates[:MAX_ITEMS]]
```

- [ ] **Step 2: Verificar manualmente a seleção e o pruning com dados fake**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
from datetime import datetime, timezone, timedelta
import daily_digest as d

now = datetime.now(timezone.utc)
items = [
    {'url': 'a', 'signal': 5, 'publishedAt': (now - timedelta(hours=2)).isoformat(timespec='seconds')},
    {'url': 'b', 'signal': 4, 'publishedAt': (now - timedelta(hours=3)).isoformat(timespec='seconds')},
    {'url': 'c', 'signal': 3, 'publishedAt': (now - timedelta(hours=1)).isoformat(timespec='seconds')},  # sinal baixo, fora
    {'url': 'd', 'signal': 5, 'publishedAt': (now - timedelta(hours=30)).isoformat(timespec='seconds')},  # fora da janela
    {'url': 'e', 'signal': 5, 'publishedAt': (now - timedelta(hours=1)).isoformat(timespec='seconds')},
    {'url': 'f', 'signal': 5, 'publishedAt': (now - timedelta(hours=4)).isoformat(timespec='seconds')},  # sobra, corta no top 3
]
sent = {}
selected = d.select_digest_items(items, sent)
print('selecionados:', [it['url'] for it in selected])
assert [it['url'] for it in selected] == ['e', 'a', 'f'], 'esperado e,a,f (sinal 5, mais recentes primeiro: e=1h, a=2h, f=4h atrás)'

# já enviado não repete
sent2 = {'a': now.isoformat(timespec='seconds')}
selected2 = d.select_digest_items(items, sent2)
assert 'a' not in [it['url'] for it in selected2]
print('dedup OK')

# prune remove antigo, mantém recente
sent3 = {
    'old': (now - timedelta(days=5)).isoformat(timespec='seconds'),
    'recent': (now - timedelta(hours=10)).isoformat(timespec='seconds'),
}
pruned = d.prune_sent(sent3)
assert pruned == {'recent': sent3['recent']}
print('prune OK')
print('TUDO OK')
"
```

Expected: imprime `selecionados: ['a', 'e', 'f']`, `dedup OK`, `prune OK`, `TUDO OK`, sem `AssertionError`.

- [ ] **Step 3: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/daily_digest.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/daily_digest.py
git commit -m "Adiciona lógica de seleção e controle de itens já enviados do resumo diário"
```

---

### Task 2: Escrita no Notion

**Files:**
- Modify: `scripts/daily_digest.py` (adicionar função nova, após `select_digest_items`)

**Interfaces:**
- Produces: `send_to_notion(item: dict, token: str, database_id: str) -> bool` (True em sucesso, nunca lança exceção).

- [ ] **Step 1: Adicionar a função de escrita no Notion**

```python
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def send_to_notion(item, token, database_id):
    """Cria uma linha na database do Notion pro item. Retorna True em
    sucesso, False em falha — nunca lança, quem chama decide o que fazer."""
    try:
        r = requests.post(
            f"{NOTION_API_BASE}/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": database_id},
                "properties": {
                    "Headline": {"title": [{"text": {"content": item.get("headline", "")[:2000]}}]},
                    "Categoria": {"select": {"name": item.get("tagLabel") or item.get("cat") or "Outro"}},
                    "Sinal": {"number": item.get("signal", 0)},
                    "Data": {"date": {"start": item.get("publishedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds")}},
                    "Gancho": {"rich_text": [{"text": {"content": item.get("hook", "")[:2000]}}]},
                    "Link": {"url": item.get("url") or None},
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[digest] falhou escrever no Notion pra '{item.get('headline', '')[:50]}': {e}", file=sys.stderr)
        return False
```

- [ ] **Step 2: Verificar manualmente que uma chave/database inválida falha graciosamente (sem lançar)**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import daily_digest as d

item = {'headline': 'Teste', 'tagLabel': 'Viral', 'signal': 5, 'publishedAt': '2026-08-10T12:00:00+00:00', 'hook': 'gancho teste', 'url': 'https://exemplo.com'}
result = d.send_to_notion(item, 'token-invalido', 'database-invalida')
print('resultado:', result)
assert result is False
print('OK — falhou graciosamente, sem lançar exceção')
"
```

Expected: imprime uma linha `[digest] falhou escrever no Notion...` no stderr, depois `resultado: False` e `OK — falhou graciosamente, sem lançar exceção`.

- [ ] **Step 3: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/daily_digest.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/daily_digest.py
git commit -m "Adiciona escrita no Notion pro resumo diário"
```

---

### Task 3: Mensagem e envio pro Telegram

**Files:**
- Modify: `scripts/daily_digest.py` (adicionar funções novas, após `send_to_notion`)

**Interfaces:**
- Produces: `build_telegram_message(items: list[dict]) -> str`, `send_to_telegram(text: str, bot_token: str, chat_ids: list[str]) -> bool` (True se pelo menos um envio funcionou).

- [ ] **Step 1: Adicionar as funções de mensagem e envio**

```python
TELEGRAM_API_BASE = "https://api.telegram.org"


def _escape_html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_telegram_message(items):
    lines = ["<b>🎯 Resumo de hoje — VIGIA GTA VI</b>", ""]
    for i, item in enumerate(items, start=1):
        headline = _escape_html(item.get("headline", ""))
        hook = _escape_html(item.get("hook", ""))
        url = item.get("url", "")
        lines.append(f"{i}. <b>{headline}</b>")
        lines.append(hook)
        if url:
            lines.append(f'<a href="{url}">ver fonte</a>')
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
```

- [ ] **Step 2: Verificar manualmente a formatação da mensagem e o escape de HTML**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import daily_digest as d

items = [
    {'headline': 'GTA 6 <trailer> & novidades', 'hook': 'gancho 1', 'url': 'https://exemplo.com/1'},
    {'headline': 'Segundo item', 'hook': 'gancho 2', 'url': 'https://exemplo.com/2'},
]
msg = d.build_telegram_message(items)
print(msg)
assert '&lt;trailer&gt;' in msg, 'HTML não escapado corretamente'
assert '1. <b>' in msg and '2. <b>' in msg, 'numeração ausente'
print('OK — escape e numeração corretos')
"
```

Expected: imprime a mensagem formatada com `&lt;trailer&gt;` (não `<trailer>` cru), termina em `OK — escape e numeração corretos`.

- [ ] **Step 3: Verificar manualmente que token/chat_id inválido falha graciosamente**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import daily_digest as d

result = d.send_to_telegram('teste', 'token-invalido', ['123', '456'])
print('resultado:', result)
assert result is False
print('OK — falhou graciosamente pros dois chat_ids, sem lançar exceção')
"
```

Expected: duas linhas `[digest] falhou mandar Telegram...` no stderr (uma por chat_id), depois `resultado: False` e a linha final `OK`.

- [ ] **Step 4: Verificar sintaxe e commit**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/daily_digest.py" && echo "compila OK"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/daily_digest.py
git commit -m "Adiciona formatação e envio da mensagem do Telegram"
```

---

### Task 4: Orquestração (main)

**Files:**
- Modify: `scripts/daily_digest.py` (adicionar `main()` no fim do arquivo)

**Interfaces:**
- Consumes: `load_items`, `load_sent`, `save_sent`, `prune_sent`, `select_digest_items` (Task 1), `send_to_notion` (Task 2), `build_telegram_message`, `send_to_telegram` (Task 3).
- Produces: `main() -> None`.

- [ ] **Step 1: Adicionar `main()` no fim do arquivo**

```python
def main():
    items = load_items()
    sent = prune_sent(load_sent())
    selected = select_digest_items(items, sent)

    if not selected:
        print("[digest] nenhum item qualificado nas últimas 24h, nada a enviar.")
        save_sent(sent)
        return

    notion_token = os.environ.get("NOTION_TOKEN")
    notion_db = os.environ.get("NOTION_DATABASE_ID")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_ids = os.environ.get("TELEGRAM_CHAT_ID", "")

    if notion_token and notion_db:
        for item in selected:
            send_to_notion(item, notion_token, notion_db)
    else:
        print("[digest] NOTION_TOKEN/NOTION_DATABASE_ID não definidos, pulando Notion.", file=sys.stderr)

    if telegram_token and telegram_chat_ids:
        message = build_telegram_message(selected)
        send_to_telegram(message, telegram_token, telegram_chat_ids.split(","))
    else:
        print("[digest] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos, pulando Telegram.", file=sys.stderr)

    # Marca como enviado assim que SELECIONADO pra rodada, independente de
    # Notion/Telegram terem tido sucesso individualmente — é só uma trava
    # anti-duplicata pra janela de 24h sobreposta entre dias, não um retry.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in selected:
        sent[item["url"]] = now_iso
    save_sent(sent)

    print(f"OK — {len(selected)} item(ns) no resumo de hoje.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar manualmente o fluxo completo contra o `data.json` real do repositório de teste (sem credenciais reais — deve rodar até o fim sem lançar, e não escrever nada em Notion/Telegram)**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
/c/Python313/python.exe scripts/daily_digest.py
```

Expected: roda até o fim sem traceback. Se houver itens com `signal >= 4` nas últimas 24h no `data.json` atual, imprime `[digest] NOTION_TOKEN/NOTION_DATABASE_ID não definidos, pulando Notion.` e `[digest] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos, pulando Telegram.` no stderr, seguido de `OK — N item(ns) no resumo de hoje.`. Se não houver itens qualificados, imprime só `[digest] nenhum item qualificado nas últimas 24h, nada a enviar.`. Confira que `digest_sent.json` foi criado/atualizado na raiz do repositório:

```bash
cat "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/digest_sent.json" 2>&1 | head -5
```

- [ ] **Step 3: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/daily_digest.py digest_sent.json
git commit -m "Adiciona orquestração (main) do resumo diário"
```

---

### Task 5: Workflow do GitHub Actions

**Files:**
- Create: `.github/workflows/digest.yml`

**Interfaces:** nenhuma (configuração).

- [ ] **Step 1: Criar o workflow**

```yaml
name: Resumo diário VIGIA GTA VI

on:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Instalar dependências
        run: pip install -r requirements.txt

      - name: Rodar resumo diário
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python scripts/daily_digest.py

      - name: Commitar digest_sent.json se mudou
        run: |
          git config user.name "vigia-bot"
          git config user.email "vigia-bot@users.noreply.github.com"
          git add digest_sent.json
          git diff --cached --quiet || git commit -m "digest: atualiza itens já enviados $(date -u +'%Y-%m-%d %H:%M UTC')"
          git push
```

- [ ] **Step 2: Verificar que o YAML é válido**

```bash
/c/Python313/python.exe -c "
import yaml
yaml.safe_load(open('D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/.github/workflows/digest.yml', encoding='utf-8'))
print('YAML válido')
"
```

Expected: `YAML válido`. Se `ModuleNotFoundError: No module named 'yaml'`, rode `/c/Python313/python.exe -m pip install --quiet pyyaml` primeiro e repita.

- [ ] **Step 3: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add .github/workflows/digest.yml
git commit -m "Adiciona workflow do resumo diário (cron 1x/dia + disparo manual)"
```

---

### Task 6: Modo guiado no setup.sh pras credenciais novas

**Files:**
- Modify: `setup.sh:75-77` (inserir bloco novo entre o bloco de `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` e o `sleep 3` que dispara a varredura — o número de linha exato pode ter mudado, localizar pelo texto `sleep 3` que vem logo antes de `gh workflow run sweep.yml`)

**Interfaces:** nenhuma (script de shell).

- [ ] **Step 1: Inserir o bloco interativo, logo antes da linha `sleep 3`**

```bash
echo ""
echo "--- Resumo diário (Telegram + Notion) — opcional ---"
read -p "Configurar agora? (s/N) " CONFIGURE_DIGEST
if [ "$CONFIGURE_DIGEST" = "s" ] || [ "$CONFIGURE_DIGEST" = "S" ]; then
  echo ""
  echo "Telegram:"
  echo "1. Abra https://t.me/BotFather no Telegram, mande /newbot e siga as instruções."
  echo "2. Copie o token que ele te der (formato tipo 123456:ABC-DEF...)."
  read -p "Cole o TELEGRAM_BOT_TOKEN (ou Enter pra pular): " TELEGRAM_BOT_TOKEN
  if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "3. Cada pessoa que vai receber o resumo deve mandar /start pro bot criado."
    echo "4. Depois, abra no navegador: https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
    echo "   e ache o \"chat\":{\"id\":...} de cada pessoa."
    read -p "Cole os chat_ids separados por vírgula (ou Enter pra pular): " TELEGRAM_CHAT_ID
  fi
  echo ""
  echo "Notion:"
  echo "1. Abra https://www.notion.so/my-integrations e crie uma integração nova."
  echo "2. Copie o \"Internal Integration Secret\"."
  read -p "Cole o NOTION_TOKEN (ou Enter pra pular): " NOTION_TOKEN
  if [ -n "$NOTION_TOKEN" ]; then
    echo "3. Crie uma database no Notion com as colunas: Headline (title), Categoria (select),"
    echo "   Sinal (number), Data (date), Gancho (text), Link (url)."
    echo "4. Compartilhe essa database com a integração (\"...\" no canto > Add connections)."
    echo "5. Copie o ID da database da URL (os 32 caracteres depois do nome da página, antes de \"?v=\")."
    read -p "Cole o NOTION_DATABASE_ID (ou Enter pra pular): " NOTION_DATABASE_ID
  fi

  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    gh secret set TELEGRAM_BOT_TOKEN --body "$TELEGRAM_BOT_TOKEN" --repo "$OWNER/$REPO_NAME"
    echo "Secret TELEGRAM_BOT_TOKEN configurada."
  fi
  if [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    gh secret set TELEGRAM_CHAT_ID --body "$TELEGRAM_CHAT_ID" --repo "$OWNER/$REPO_NAME"
    echo "Secret TELEGRAM_CHAT_ID configurada."
  fi
  if [ -n "${NOTION_TOKEN:-}" ]; then
    gh secret set NOTION_TOKEN --body "$NOTION_TOKEN" --repo "$OWNER/$REPO_NAME"
    echo "Secret NOTION_TOKEN configurada."
  fi
  if [ -n "${NOTION_DATABASE_ID:-}" ]; then
    gh secret set NOTION_DATABASE_ID --body "$NOTION_DATABASE_ID" --repo "$OWNER/$REPO_NAME"
    echo "Secret NOTION_DATABASE_ID configurada."
  fi
else
  echo "Pulei a configuração do resumo diário — roda o setup.sh de novo quando quiser configurar."
fi
```

- [ ] **Step 2: Verificar a sintaxe do bash**

```bash
bash -n "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/setup.sh" && echo "sintaxe OK"
```

Expected: `sintaxe OK`, sem erro de parsing.

- [ ] **Step 3: Verificar manualmente que responder "N" (ou Enter) pula o bloco sem pedir nada**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
printf 'N\n' | bash -c '
CONFIGURE_DIGEST_TEST=$(printf "N\n")
echo "$CONFIGURE_DIGEST_TEST" | grep -qi "^s$" && echo "ENTROU NO BLOCO (errado)" || echo "PULOU O BLOCO (correto)"
'
```

Expected: `PULOU O BLOCO (correto)` — confirma que a lógica de comparação `"$CONFIGURE_DIGEST" = "s"` só entra no bloco com "s"/"S" explícito.

- [ ] **Step 4: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add setup.sh
git commit -m "Adiciona modo guiado no setup.sh pras credenciais do resumo diário"
```

---

### Task 7: Validação end-to-end (requer credenciais reais do usuário)

**Files:** nenhum (só execução/verificação).

**Interfaces:** nenhuma nova — valida o comportamento de ponta a ponta.

**Pré-requisito:** esta task não pode ser concluída sem o usuário fornecer credenciais reais (um bot do Telegram criado por ele, chat_ids reais, uma integração e database do Notion criadas por ele) — isso não pode ser feito por um agente, exige login pessoal do usuário no Telegram/Notion. Se as credenciais ainda não estiverem disponíveis quando chegar nesta task, pare aqui e reporte ao controlador/usuário exatamente o que falta (uma das quatro credenciais, ou todas), em vez de marcar como bloqueado silenciosamente.

- [ ] **Step 1: Confirmar que o usuário forneceu as 4 credenciais (ou decidiu testar só um dos dois canais)**

Perguntar ao usuário se as credenciais já foram geradas (seguindo as instruções que aparecem ao rodar `./setup.sh` com "s" no prompt do Task 6), ou configurar manualmente via:

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh secret set TELEGRAM_BOT_TOKEN --body "<valor fornecido pelo usuário>" --repo Prysiaznyj/vigia-gta6-test
gh secret set TELEGRAM_CHAT_ID --body "<valor fornecido pelo usuário>" --repo Prysiaznyj/vigia-gta6-test
gh secret set NOTION_TOKEN --body "<valor fornecido pelo usuário>" --repo Prysiaznyj/vigia-gta6-test
gh secret set NOTION_DATABASE_ID --body "<valor fornecido pelo usuário>" --repo Prysiaznyj/vigia-gta6-test
gh secret list --repo Prysiaznyj/vigia-gta6-test
```

- [ ] **Step 2: Push de tudo e disparo manual do workflow**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git push
gh workflow run digest.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar ~30-60s, depois:

```bash
gh run list --repo Prysiaznyj/vigia-gta6-test --limit 1
```

Pegar o `run id` e:

```bash
gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --log 2>&1 | grep -iE "digest|notion|telegram|OK —|error|traceback"
```

Expected: status final `success`. Se `NOTION_TOKEN`/`NOTION_DATABASE_ID` configurados, sem linha `falhou escrever no Notion`. Se `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` configurados, sem linha `falhou mandar Telegram`.

- [ ] **Step 3: Confirmar recebimento real**

Pedir ao usuário para confirmar visualmente: a mensagem chegou no Telegram (dele e da outra pessoa, se ambos os chat_ids foram configurados)? A linha nova apareceu na database do Notion, com as colunas certas preenchidas?

- [ ] **Step 4: Reportar ao usuário e aguardar aprovação antes de portar pra produção**

Não fazer merge/port pro repositório `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` nesta task — decisão explícita do usuário, fora do escopo deste plano.
