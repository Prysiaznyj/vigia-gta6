# Notion como arquivo completo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover a escrita no Notion de `daily_digest.py` (1x/dia, só os 3 itens curados) pra `fetch_signals.py` (a cada 4h, todo item novo de qualquer fonte), transformando o Notion num arquivo completo e buscável — o Telegram continua sendo o empurrão curado, sem duplicar responsabilidade.

**Architecture:** `fetch_signals.py` ganha uma função de arquivamento (`archive_to_notion`) chamada em `main()` logo depois de `new_items` ser calculado — escreve cada item novo que ainda não foi arquivado (controle por URL em `notion_archived.json`, mesmo padrão de `digest_sent.json`). `daily_digest.py` perde toda a lógica de Notion, ficando só com Telegram. Os workflows trocam de dono das credenciais `NOTION_TOKEN`/`NOTION_DATABASE_ID`: saem de `digest.yml`, entram em `sweep.yml`.

**Tech Stack:** Python 3.11/3.13, sem dependência nova (usa `requests`, já presente nos dois scripts).

## Global Constraints

- Spec de referência: `docs/superpowers/specs/2026-08-10-notion-arquivo-completo-design.md`.
- Todo o trabalho acontece em `D:\Clientes\8 - GTA VI\NOSSO APP\vigia-gta6-test` — nunca commitar/pushar direto em `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` durante este plano.
- **Pré-requisito já cumprido pelo controller, fora deste plano:** a coluna **Fonte** (tipo `select`, opções `Notícia`/`Reddit`/`YouTube`) já foi adicionada na database real do Notion ("GTA IDEAS", id `52b1f0f59da847a9a3ea7e06bfe25973`) via API antes deste plano começar. Não precisa criar essa coluna — ela já existe e pode ser usada nos testes ao vivo.
- `NOTION_ARCHIVE_RETENTION_DAYS = 5` (72h de `LOOKBACK_HOURS` + folga de segurança) — valor exato, não mudar sem confirmar com o usuário.
- Mapeamento fixo de `source` pra rótulo da coluna Fonte: `news` → `"Notícia"`, `reddit` → `"Reddit"`, `youtube` → `"YouTube"`.
- `NOTION_TOKEN`/`NOTION_DATABASE_ID` já estão configurados como secrets no repositório de teste (reaproveitados do resumo diário) — nenhum novo secret precisa ser criado, só o `env:` do workflow que muda de arquivo.
- Sem dependência nova, sem suite de teste formal (verificação manual via `python -c`, mesmo padrão do projeto). Python local: `/c/Python313/python.exe`.

---

### Task 1: Arquivamento no Notion a cada varredura (`fetch_signals.py` + `sweep.yml`)

**Files:**
- Modify: `scripts/fetch_signals.py` (novas constantes, três funções de controle de estado, uma função de escrita no Notion, wiring em `main()`)
- Modify: `.github/workflows/sweep.yml` (novo `env` + `git add`)

**Interfaces:**
- Produces: `load_notion_archived() -> dict`, `save_notion_archived(archived: dict) -> None`, `prune_notion_archived(archived: dict) -> dict`, `archive_to_notion(new_items: list[dict], archived: dict, token: str, database_id: str) -> None` (atualiza `archived` in-place, uma chave por URL arquivada com sucesso).

- [ ] **Step 1: Adicionar constantes, logo depois de `CHANNEL_BASELINE_FILE = os.path.abspath(CHANNEL_BASELINE_FILE)` (linha 32 no estado atual)**

```python
NOTION_ARCHIVE_FILE = os.path.join(os.path.dirname(__file__), "..", "notion_archived.json")
NOTION_ARCHIVE_FILE = os.path.abspath(NOTION_ARCHIVE_FILE)
NOTION_ARCHIVE_RETENTION_DAYS = 5
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_SOURCE_LABEL = {"news": "Notícia", "reddit": "Reddit", "youtube": "YouTube"}
```

- [ ] **Step 2: Escrever as três funções de controle de estado, logo antes de `def main():` (localizar por `def _trim_with_quotas(combined, max_items):` — as funções novas entram ANTES dela, já que `_trim_with_quotas` deve continuar sendo a última função antes de `main()`)**

```python
def load_notion_archived():
    if not os.path.exists(NOTION_ARCHIVE_FILE):
        return {}
    try:
        with open(NOTION_ARCHIVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[notion] falhou ler {NOTION_ARCHIVE_FILE}, começando do zero: {e}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_notion_archived(archived):
    with open(NOTION_ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archived, f, ensure_ascii=False, indent=2)


def prune_notion_archived(archived):
    """Remove entradas com mais de NOTION_ARCHIVE_RETENTION_DAYS dias — item
    que já saiu da janela de busca (LOOKBACK_HOURS) nunca mais pode
    reaparecer como 'novo', então não precisa ficar guardado pra sempre."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=NOTION_ARCHIVE_RETENTION_DAYS)
    kept = {}
    for url, archived_at in archived.items():
        try:
            if datetime.fromisoformat(archived_at) >= cutoff:
                kept[url] = archived_at
        except Exception:
            continue
    return kept


def archive_to_notion(new_items, archived, token, database_id):
    """Escreve no Notion todo item de new_items que ainda não foi arquivado
    (controle por URL em 'archived', atualizado in place). Uma falha
    isolada loga em stderr e segue pro próximo item — não aborta a rodada.
    Item só é marcado como arquivado em caso de sucesso, pra tentar de novo
    na próxima rodada se a escrita falhar."""
    for item in new_items:
        url = item.get("url")
        if not url or url in archived:
            continue
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
                        "Link": {"url": url},
                        "Fonte": {"select": {"name": NOTION_SOURCE_LABEL.get(item.get("source"), "Outro")}},
                    },
                },
                timeout=15,
            )
            r.raise_for_status()
            archived[url] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except Exception as e:
            print(f"[notion] falhou arquivar '{item.get('headline', '')[:50]}': {e}", file=sys.stderr)
```

- [ ] **Step 3: Chamar o arquivamento em `main()`, logo depois de `save_channel_baselines(baselines)`**

Em `main()` (localizar por `new_items = build_items(existing_items, baselines)`), o trecho atual é:
```python
    new_items = build_items(existing_items, baselines)
    save_channel_baselines(baselines)

    combined = new_items + existing_items
```
Substituir por:
```python
    new_items = build_items(existing_items, baselines)
    save_channel_baselines(baselines)

    notion_token = os.environ.get("NOTION_TOKEN")
    notion_db = os.environ.get("NOTION_DATABASE_ID")
    if notion_token and notion_db:
        archived = prune_notion_archived(load_notion_archived())
        archive_to_notion(new_items, archived, notion_token, notion_db)
        save_notion_archived(archived)
    else:
        print("[notion] NOTION_TOKEN/NOTION_DATABASE_ID não definidos, pulando arquivamento.", file=sys.stderr)

    combined = new_items + existing_items
```

- [ ] **Step 4: Verificar sintaxe**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/fetch_signals.py" && echo "compila OK"
```

- [ ] **Step 5: Verificar `prune_notion_archived` isoladamente, sem rede**

```bash
/c/Python313/python.exe -c "
import sys
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import fetch_signals as fs
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
archived = {
    'url-recente': (now - timedelta(days=1)).isoformat(timespec='seconds'),
    'url-na-borda': (now - timedelta(days=4, hours=23)).isoformat(timespec='seconds'),
    'url-velho': (now - timedelta(days=6)).isoformat(timespec='seconds'),
    'url-corrompido': 'nao-e-uma-data',
}
result = fs.prune_notion_archived(archived)
assert 'url-recente' in result
assert 'url-na-borda' in result
assert 'url-velho' not in result
assert 'url-corrompido' not in result
print('OK — prune mantém recentes e remove velhos/corrompidos:', sorted(result.keys()))
"
```

Expected: imprime `OK — prune mantém recentes e remove velhos/corrompidos: ['url-na-borda', 'url-recente']`.

- [ ] **Step 6: Verificar `archive_to_notion` ao vivo contra a database real de teste (credenciais já configuradas no repo — a coluna Fonte já existe, adicionada antes deste plano começar)**

```bash
/c/Python313/python.exe -c "
import sys, os
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import fetch_signals as fs

token = os.environ.get('NOTION_TOKEN')
db = os.environ.get('NOTION_DATABASE_ID')
assert token and db, 'defina NOTION_TOKEN e NOTION_DATABASE_ID no ambiente antes de rodar este teste'

items = [
    {'headline': '[TESTE PLANO] item de notícia', 'tagLabel': 'Viral', 'cat': 'viral', 'signal': 3, 'publishedAt': '2026-08-10T12:00:00+00:00', 'hook': 'gancho de teste', 'url': 'https://example.com/teste-plano-notion-1', 'source': 'news'},
    {'headline': '[TESTE PLANO] item de reddit', 'tagLabel': 'Viral', 'cat': 'viral', 'signal': 2, 'publishedAt': '2026-08-10T12:00:00+00:00', 'hook': 'gancho de teste', 'url': 'https://example.com/teste-plano-notion-2', 'source': 'reddit'},
]
archived = {}
fs.archive_to_notion(items, archived, token, db)
assert len(archived) == 2, f'esperado 2 arquivados, veio {len(archived)}: {archived}'
print('OK — 2 itens arquivados no Notion:', list(archived.keys()))

# rodar de novo com o MESMO archived: não deve criar linha duplicada (dedup por URL)
fs.archive_to_notion(items, archived, token, db)
print('OK — segunda chamada não duplicou (archived continua com 2 chaves):', len(archived) == 2)
"
```

Expected: imprime `OK — 2 itens arquivados no Notion: [...]` e depois `OK — segunda chamada não duplicou...: True`. Depois de rodar, confirmar manualmente (ou via API) que as 2 linhas `[TESTE PLANO]` apareceram na database "GTA IDEAS" com a coluna Fonte preenchida (`Notícia` e `Reddit`) — e depois apagar essas 2 linhas de teste da database (são só pra validar o código, não fazem parte do arquivo real).

- [ ] **Step 7: Atualizar `.github/workflows/sweep.yml`**

Trocar:
```yaml
      - name: Rodar varredura
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: python scripts/fetch_signals.py

      - name: Commitar data.json se mudou
        run: |
          git config user.name "vigia-bot"
          git config user.email "vigia-bot@users.noreply.github.com"
          git add data.json channel_baselines.json
          git diff --cached --quiet || git commit -m "sweep: atualiza sinais $(date -u +'%Y-%m-%d %H:%M UTC')"
          git push
```
por:
```yaml
      - name: Rodar varredura
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python scripts/fetch_signals.py

      - name: Commitar data.json se mudou
        run: |
          git config user.name "vigia-bot"
          git config user.email "vigia-bot@users.noreply.github.com"
          git add data.json channel_baselines.json notion_archived.json
          git diff --cached --quiet || git commit -m "sweep: atualiza sinais $(date -u +'%Y-%m-%d %H:%M UTC')"
          git push
```

- [ ] **Step 8: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/fetch_signals.py .github/workflows/sweep.yml
git commit -m "Adiciona arquivamento completo no Notion a cada varredura de 4h"
```

---

### Task 2: Remover Notion do resumo diário (`daily_digest.py` + `digest.yml`)

**Files:**
- Modify: `scripts/daily_digest.py` (remove `send_to_notion`, constantes `NOTION_API_BASE`/`NOTION_VERSION`, lógica de Notion em `main()`, docstring)
- Modify: `.github/workflows/digest.yml` (remove `NOTION_TOKEN`/`NOTION_DATABASE_ID` do `env`)

**Interfaces:**
- Consumes: nenhuma nova (só remove código).
- Produces: `main()` de `daily_digest.py` continua com a mesma assinatura (`main() -> None`, chamado via `if __name__ == "__main__":`), mas só cuida de Telegram.

- [ ] **Step 1: Atualizar a docstring do arquivo**

Trocar (linhas 1-13 no estado atual):
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
```
por:
```python
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
```

- [ ] **Step 2: Remover `send_to_notion` e as constantes `NOTION_API_BASE`/`NOTION_VERSION`**

Remover o bloco inteiro (localizar por `NOTION_API_BASE = "https://api.notion.com/v1"`):
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
(a linha em branco dupla que sobra antes de `TELEGRAM_API_BASE = "https://api.telegram.org"` deve virar uma linha em branco dupla normal — não remover as duas linhas em branco que já separam as seções, só o bloco de código do Notion).

- [ ] **Step 3: Simplificar `main()` pra só Telegram**

Trocar o corpo inteiro de `main()`:
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

    notion_tried = notion_ok = False
    telegram_tried = telegram_ok = False

    if notion_token and notion_db:
        notion_tried = True
        notion_results = [send_to_notion(item, notion_token, notion_db) for item in selected]
        notion_ok = all(notion_results)
    else:
        print("[digest] NOTION_TOKEN/NOTION_DATABASE_ID não definidos, pulando Notion.", file=sys.stderr)

    if telegram_token and telegram_chat_ids:
        message = build_telegram_message(selected)
        telegram_tried = True
        telegram_ok = send_to_telegram(message, telegram_token, telegram_chat_ids.split(","))
    else:
        print("[digest] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos, pulando Telegram.", file=sys.stderr)

    if (notion_tried or telegram_tried) and not (notion_ok or telegram_ok):
        print("[digest] TODOS os canais configurados falharam — nada foi entregue. Itens NÃO marcados como enviados (tentativa de novo na próxima rodada).", file=sys.stderr)
        sys.exit(1)

    # Marca como enviado assim que SELECIONADO pra rodada (e pelo menos um canal
    # teve sucesso, ou nenhum canal estava configurado), independente de os dois
    # canais terem tido sucesso individualmente — é só uma trava anti-duplicata
    # pra janela de 24h sobreposta entre dias, não um retry completo.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in selected:
        sent[item["url"]] = now_iso
    save_sent(sent)

    print(f"OK — {len(selected)} item(ns) no resumo de hoje.")
```
por:
```python
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
```

- [ ] **Step 4: Verificar sintaxe e que não sobrou referência a Notion**

```bash
/c/Python313/python.exe -m py_compile "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/daily_digest.py" && echo "compila OK"
grep -in "notion" "D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts/daily_digest.py" || echo "OK — nenhuma referência a Notion sobrou"
```

Expected: `compila OK`, depois `OK — nenhuma referência a Notion sobrou`.

- [ ] **Step 5: Verificar `main()` manualmente com Telegram mockado (sem rede) — três cenários**

```bash
/c/Python313/python.exe -c "
import sys, os, json, tempfile
sys.path.insert(0, 'D:/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test/scripts')
import daily_digest as dd
from datetime import datetime, timezone

tmp_data = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
tmp_sent = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
tmp_sent.write('{}')
tmp_sent.close()
now = datetime.now(timezone.utc).isoformat(timespec='seconds')
json.dump({'items': [{'url': 'https://x/1', 'headline': 'h', 'hook': 'g', 'signal': 5, 'publishedAt': now, 'tagLabel': 'Viral', 'cat': 'viral'}]}, tmp_data)
tmp_data.close()
dd.DATA_FILE = tmp_data.name
dd.DIGEST_SENT_FILE = tmp_sent.name

# Cenário 1: sem TELEGRAM_* no ambiente -> sai sem erro, sem marcar como enviado
os.environ.pop('TELEGRAM_BOT_TOKEN', None)
os.environ.pop('TELEGRAM_CHAT_ID', None)
dd.main()
sent_after = json.load(open(tmp_sent.name, encoding='utf-8'))
assert sent_after == {}, f'nao deveria marcar como enviado sem credencial: {sent_after}'
print('Cenario 1 (sem credencial) -> OK, saiu sem marcar nada')

# Cenário 2: TELEGRAM configurado mas send_to_telegram falha -> sys.exit(1), sem marcar
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake'
os.environ['TELEGRAM_CHAT_ID'] = '123'
dd.send_to_telegram = lambda *a, **k: False
try:
    dd.main()
    print('Cenario 2 -> FALHOU, deveria ter chamado sys.exit(1)')
except SystemExit as e:
    assert e.code == 1
    sent_after = json.load(open(tmp_sent.name, encoding='utf-8'))
    assert sent_after == {}, f'nao deveria marcar como enviado se telegram falhou: {sent_after}'
    print('Cenario 2 (telegram falha) -> OK, sys.exit(1) e nada marcado')

# Cenário 3: TELEGRAM configurado e funciona -> marca como enviado, sem sys.exit
dd.send_to_telegram = lambda *a, **k: True
dd.main()
sent_after = json.load(open(tmp_sent.name, encoding='utf-8'))
assert 'https://x/1' in sent_after, f'deveria ter marcado como enviado: {sent_after}'
print('Cenario 3 (telegram funciona) -> OK, item marcado como enviado')

os.unlink(tmp_data.name)
os.unlink(tmp_sent.name)
print('TUDO OK')
"
```

Expected: imprime os 3 cenários com `OK` e termina em `TUDO OK`.

- [ ] **Step 6: Atualizar `.github/workflows/digest.yml`**

Trocar:
```yaml
      - name: Rodar resumo diário
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python scripts/daily_digest.py
```
por:
```yaml
      - name: Rodar resumo diário
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python scripts/daily_digest.py
```

- [ ] **Step 7: Commit**

```bash
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git add scripts/daily_digest.py .github/workflows/digest.yml
git commit -m "Remove escrita no Notion do resumo diário — Telegram fica com a curadoria, Notion vira arquivo completo via varredura"
```

---

### Task 3: Validação end-to-end no repositório de teste

**Files:** nenhum (só execução/verificação).

**Interfaces:** nenhuma nova — valida o comportamento de ponta a ponta das Tasks 1 e 2 juntas, com dados reais.

- [ ] **Step 1: Push e disparo manual do `sweep.yml` real**

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
cd "/d/Clientes/8 - GTA VI/NOSSO APP/vigia-gta6-test"
git fetch origin
git rebase origin/main
git push
gh workflow run sweep.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar a conclusão (`gh run list --repo Prysiaznyj/vigia-gta6-test --limit 1`, depois `gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --json status,conclusion` até `status` virar `completed`).

- [ ] **Step 2: Checar os logs em busca de erro**

```bash
gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --log 2>&1 | grep -iE "notion|OK —|error|traceback|falhou"
```

Expected: status final `success`, linha `OK — N itens novos, M no total.`, sem traceback Python não tratado. Linhas `[notion] falhou arquivar '...'` isoladas (um item específico falhando) são aceitáveis — o requisito é não ter uma exceção que aborte a rodada inteira.

- [ ] **Step 3: Confirmar que as linhas apareceram na database do Notion, com a coluna Fonte preenchida**

Exportar `NOTION_TOKEN` no shell antes de rodar (mesmo valor já configurado como secret do repositório — nunca colar o valor literal em nenhum arquivo commitado, o GitHub bloqueia o push se detectar):
```bash
export NOTION_TOKEN="<mesmo valor do secret NOTION_TOKEN>"
```

```bash
SCRATCH="C:/Users/lucas/AppData/Local/Temp/claude/C--Users-lucas/450e1f14-02cb-4b1f-a0f0-f3338a4c807d/scratchpad"
cat > "$SCRATCH/notion_query.json" << 'EOF'
{"page_size": 10, "sorts": [{"timestamp": "created_time", "direction": "descending"}]}
EOF
curl -s -X POST "https://api.notion.com/v1/databases/52b1f0f59da847a9a3ea7e06bfe25973/query" \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d @"$SCRATCH/notion_query.json" > "$SCRATCH/notion_result.json"
/c/Python313/python.exe -c "
import json
with open(r'C:\Users\lucas\AppData\Local\Temp\claude\C--Users-lucas\450e1f14-02cb-4b1f-a0f0-f3338a4c807d\scratchpad\notion_result.json', encoding='utf-8') as f:
    d = json.load(f)
for r in d.get('results', [])[:10]:
    p = r['properties']
    title = ''.join(t['plain_text'] for t in p.get('Headline', {}).get('title', []))
    fonte = (p.get('Fonte', {}) or {}).get('select') or {}
    print(fonte.get('name', 'SEM FONTE'), '|', title[:60])
"
rm -f "$SCRATCH/notion_query.json" "$SCRATCH/notion_result.json"
```

Expected: várias linhas novas (mais que as 3 do resumo diário — deve incluir Reddit e YouTube também, não só notícia), cada uma com `Fonte` preenchida como `Notícia`, `Reddit` ou `YouTube` (nenhuma como `SEM FONTE`).

- [ ] **Step 4: Confirmar que uma segunda rodada não duplica linhas já arquivadas**

```bash
gh workflow run sweep.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar conclusão, repetir o Step 3 e conferir manualmente que os itens que já apareciam antes não geraram uma segunda linha idêntica (comparar contagem de linhas com o mesmo `Headline`/`Link` — deve continuar 1 cada, só itens genuinamente novos desta rodada devem ter aparecido a mais).

- [ ] **Step 5: Validar que o resumo diário continua funcionando só com Telegram**

```bash
gh workflow run digest.yml --repo Prysiaznyj/vigia-gta6-test
```

Aguardar conclusão, checar logs (`gh run view <run-id> --repo Prysiaznyj/vigia-gta6-test --log 2>&1 | grep -iE "digest|telegram|OK —|error"`) — esperado `OK — N item(ns) no resumo de hoje.` sem nenhuma menção a Notion, e pedir ao usuário pra confirmar visualmente que a mensagem chegou no Telegram normalmente.

- [ ] **Step 6: Reportar ao usuário e aguardar aprovação antes de portar pra produção**

Não fazer merge/port pro repositório `vigia-gta6-site` / `Prysiaznyj/vigia-gta6` nesta task — decisão explícita do usuário, fora do escopo deste plano. Lembrar o usuário do risco de duplicação já identificado na spec: depois do port, remover `NOTION_TOKEN`/`NOTION_DATABASE_ID` dos secrets do repositório de teste (mesma solução já aplicada pro cron do resumo diário), senão teste e produção arquivam os mesmos itens em dobro.
