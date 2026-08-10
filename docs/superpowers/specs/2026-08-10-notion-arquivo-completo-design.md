# Notion como arquivo completo (não só o resumo diário) — design

**Data:** 2026-08-10

## Contexto e objetivo

Hoje o `daily_digest.py` escreve no Notion só os 3 itens selecionados pro
resumo diário (`signal >= 4`, últimas 24h) — a mesma seleção que vai pro
Telegram. Na prática o Notion acaba sendo um espelho pequeno do Telegram,
não um arquivo de verdade.

Objetivo: separar as responsabilidades. **Telegram** continua sendo o
empurrão curado (só os 3 melhores/dia, pra pessoa não travar escolhendo).
**Notion** vira um arquivo completo e buscável de tudo que a ferramenta
encontra — todo item novo de toda rodada de 4h (notícia, Reddit e YouTube),
não só os destaques.

## Onde roda

Move a escrita no Notion de `daily_digest.py` (1x/dia) pra
`scripts/fetch_signals.py` (a cada 4h, junto da varredura normal). Ponto de
entrada: `main()`, logo depois de `new_items = build_items(existing_items,
baselines)` — `new_items` já é exatamente "itens genuinamente novos nesta
rodada" (já passaram pelo dedup por similaridade de headline contra
`existing_items`), então é a lista certa pra arquivar, antes do corte de
`MAX_ITEMS`.

`daily_digest.py` para de escrever no Notion — passa a cuidar só do
Telegram. Continua lendo `data.json` normalmente pra selecionar o resumo
diário (isso não muda).

## Deduplicação

Mesmo padrão já usado em `digest_sent.json`: um arquivo de controle novo,
`notion_archived.json`, guarda `{url: timestamp}` de tudo que já foi
escrito no Notion. Antes de escrever um item, verifica se a URL já está
nesse arquivo — se estiver, pula. Isso garante que um item nunca vira duas
linhas no Notion mesmo que ele seja expulso do `data.json` (corte de
`MAX_ITEMS`) numa rodada e reapareça como "novo" (dedup por headline não
pega mais, porque saiu de `existing_items`) numa rodada futura.

Entradas com mais de `LOOKBACK_HOURS` (72h, a mesma janela que
`fetch_news`/`fetch_reddit`/`fetch_youtube` já usam pra decidir o que é
"recente") mais uma folga de segurança são removidas do arquivo de controle
a cada rodada — o mesmo item nunca pode reaparecer como "novo" depois de
sair da janela de busca, então não precisa ficar guardado pra sempre.
Retenção: 5 dias (72h + folga).

## Coluna nova: Fonte

A database do Notion ("GTA IDEAS") ganha uma propriedade nova, **Fonte**
(tipo `select`), com os valores `Notícia` / `Reddit` / `YouTube` —
necessária porque o arquivo completo vai ter muito mais variedade de
origem do que os 3 itens curados de antes (hoje a database só tem
Headline/Categoria/Sinal/Data/Gancho/Link). Precisa ser adicionada
manualmente pelo usuário na database existente antes do rollout (mesmo
processo manual já usado pra criar a database originalmente).

## Credenciais

`NOTION_TOKEN`/`NOTION_DATABASE_ID` migram de secrets usados por
`digest.yml` pra secrets usados por `sweep.yml` (mesmos nomes, mesmos
valores — só muda qual workflow os lê). `digest.yml` não usa mais essas
duas variáveis. Sem alteração em `setup.sh`: os secrets já são configurados
com esses nomes, independente de qual workflow os consome.

## Tratamento de erro

Mesmo padrão do projeto: escrita no Notion em try/except próprio (já existe
como `send_to_notion` em `daily_digest.py` — a versão nova em
`fetch_signals.py` segue a mesma estrutura, com a coluna Fonte a mais),
uma falha isolada loga em stderr e segue pro próximo item, não aborta a
rodada. `notion_archived.json` corrompido/ilegível é tratado como
`channel_baselines.json` — não trava, começa do zero (pior caso: alguns
itens são re-escritos uma vez até o arquivo se reconstruir).

## Impacto em `daily_digest.py`

- Remove: `send_to_notion`, `NOTION_API_BASE`, `NOTION_VERSION`, leitura de
  `NOTION_TOKEN`/`NOTION_DATABASE_ID`, e toda a lógica de
  `notion_tried`/`notion_ok` em `main()`.
- `main()` simplifica pra só Telegram: sem credencial configurada, log e
  sai sem erro (comportamento já existente, mantido); credencial
  configurada mas envio falhou, `sys.exit(1)` (também já existente,
  mantido — só remove a parte "OU o outro canal funcionou").
- Docstring do arquivo atualizada pra refletir que só cuida do Telegram
  agora.

## Arquivos afetados

- `scripts/fetch_signals.py` — nova função de arquivamento no Notion +
  `notion_archived.json` (load/save/prune) + chamada em `main()`.
- `scripts/daily_digest.py` — remove tudo relacionado a Notion.
- `.github/workflows/sweep.yml` — ganha `NOTION_TOKEN`/`NOTION_DATABASE_ID`
  no `env` do step de varredura, e `notion_archived.json` no `git add` do
  commit automático.
- `.github/workflows/digest.yml` — remove `NOTION_TOKEN`/`NOTION_DATABASE_ID`
  do `env`.

## Isolamento e rollout

Mesmo padrão de sempre: construído e validado primeiro no repositório de
teste (`vigia-gta6-test`), incluindo a coluna "Fonte" adicionada
manualmente na database real antes de rodar. Só porta pra
`vigia-gta6-site` depois de aprovação explícita do usuário.

**Risco de duplicação pós-port:** o `sweep.yml` de teste roda a cada 4h
igual ao de produção (diferente do `digest.yml`, seu cron nunca foi
pausado). Como os dois repositórios usam a mesma database do Notion, se os
dois continuarem escrevendo no Notion depois do port, cada item real
apareceria duas vezes (uma via teste, outra via produção). Mesma solução já
usada pro cron do resumo diário: depois de portar e validar, remove
`NOTION_TOKEN`/`NOTION_DATABASE_ID` dos secrets do repositório de teste
(a escrita simplesmente é pulada sem esses dois — comportamento já
existente, "credencial ausente = pula"). `sweep.yml` de teste continua
rodando normal pra tudo mais (site de teste, futuras features).
