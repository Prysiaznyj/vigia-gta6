# Detecção de vídeos outlier no YouTube — design

Data: 2026-08-10

## Contexto e objetivo

O VIGIA hoje ordena vídeos do YouTube só por `viewCount` bruto dentro de uma janela de
72h (`LOOKBACK_HOURS`). Isso favorece sistematicamente canais grandes e não captura o
caso que mais interessa pra gerar ideia de conteúdo: um vídeo que está **performando
muito acima do normal**, seja porque é recente e já bombou, seja porque o canal que
publicou nunca teve um vídeo assim.

Objetivo desta feature: marcar vídeos como **outlier** (visualmente e na pontuação de
sinal) usando dois critérios independentes de "fora da curva", sem depender do tamanho
do canal.

**Fora de escopo aqui:** tornar a ferramenta genérica pra múltiplos nichos (médicos,
arquitetos etc.) é uma decisão de produto maior, discutida como uma iniciativa
separada — não faz parte deste design.

## Critérios de outlier

Um vídeo do YouTube é marcado `outlier: true` se bater **qualquer um** dos dois:

1. **Bombando agora**: entre os vídeos publicados nas últimas 4h retornados pela busca,
   está entre os **top 6** por visualizações.
2. **Outlier de canal**: visualizações do vídeo ≥ **2x a mediana** das visualizações
   dos últimos vídeos daquele canal. Só é avaliado se o canal tiver pelo menos 3 vídeos
   recentes na amostra (amostra menor = critério pulado pra esse vídeo, evita falso
   positivo). Mediana em vez de média pra um vídeo viral antigo do canal não distorcer
   o "normal" dele.

Os números (top 6, limiar 2x, amostra mínima 3) são constantes fáceis de ajustar depois.

## Arquitetura e fluxo de dados

Mudança central: hoje `main()` só processa itens **novos** a cada rodada; itens já
salvos no `data.json` são carregados e simplesmente recombinados sem re-pontuar. Pra
re-checar vídeos do YouTube já rastreados a cada rodada (a cada 4h), isso muda:

1. Antes de combinar itens novos + existentes, os itens de `source: youtube` já
   presentes no `data.json` têm suas visualizações atuais buscadas de novo (uma
   chamada `videos.list` batelada, cabe os até 40 itens do cap numa chamada só —
   barata em cota) e o outlier/pontuação deles é recalculado com o dado fresco.
2. `fetch_youtube()` passa a capturar e propagar `channelId` de cada vídeo (necessário
   pro critério 2, e evita ter que rebuscar isso depois via `search.list`, que é caro
   em cota).
3. A lógica de pontuação (`score_item`) é compartilhada entre item novo e item
   re-checado — não duplica a regra em dois lugares.

### Cache de baseline por canal — `channel_baselines.json`

Novo arquivo, no mesmo padrão do `data.json` (JSON simples, commitado pelo bot).
Guarda por canal: `{ channelId: { medianViews, amostra, calculadoEm } }`.

- Só recalcula o histórico de um canal (busca dos últimos uploads via
  `playlistItems` + `videos.list` pra pegar views) se o cache não existir ou tiver
  mais de 24h — evita gastar cota recomputando toda hora um número que não muda muito
  de 4 em 4h.
- A visualização **do vídeo em si** (não do histórico do canal) é sempre re-checada
  a cada rodada, independente do cache de baseline.

### Orçamento de cota estimado

- Uso atual: ~600-650 unidades/dia (bem abaixo do limite de 10.000/dia, que reseta
  à meia-noite horário do Pacífico).
- Custo extra estimado da feature: ~90 unidades/rodada (channels.list +
  playlistItems.list + videos.list, todas baratas) × 6 rodadas/dia ≈ 540/dia extra.
- Total projetado: ~1.200/dia — folga confortável.

## Schema (`data.json`)

Novos campos em itens `source: youtube`:
- `outlier: true | false`
- `channelId: string`

## UI (`index.html`)

- Selo visual "OUTLIER 🔥" no card, além da tag de categoria já existente.
- Nova opção "Outliers" no dropdown "organizar por" (reaproveita o mecanismo de
  filtro por tipo já implementado).

## Tratamento de erro

- Falha ao buscar histórico de um canal → vídeo só não é avaliado pelo critério 2
  (ainda pode virar outlier pelo critério 1). Não derruba a rodada.
- Canal novo / menos de 3 vídeos na amostra → critério 2 pulado pra esse vídeo.
- Falha na rechecagem de views dos itens existentes → itens ficam como estavam na
  rodada anterior, rodada continua normalmente.
- Mesmo padrão de resiliência já usado no resto do script: captura exceção por
  chamada externa, loga em stderr, segue em frente.

## Teste e rollout

- Sem suite de teste formal (projeto pequeno, sem infra de teste hoje) — validação
  manual: funções isoladas com dados de exemplo (mesmo padrão usado nas features
  anteriores desta sessão), depois execução real do workflow.
- **Isolamento**: a feature é construída e validada num **repositório novo e
  separado** (clone do atual, com seu próprio GitHub Pages e secrets), não na branch
  `main` do repositório de produção. O site em produção
  (https://Prysiaznyj.github.io/vigia-gta6/) não é tocado até o usuário aprovar o
  resultado no repositório de teste e pedir o merge/port pra produção.
