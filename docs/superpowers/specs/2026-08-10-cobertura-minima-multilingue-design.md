# Cobertura mínima por categoria + notícias multilíngues — design

**Data:** 2026-08-10

## Contexto e objetivo

Hoje o corte de itens (`MAX_ITEMS = 40`) protege só por categoria de conteúdo
(lançamento/trabalhista/vendas com sinal alto) — nada protege por **tipo de
fonte**. Como o Reddit "hot" recebe um valor de engajamento sintético alto
(`5000, 4750, ...`, proxy criado porque o RSS não traz contagem real de
upvotes), ele sistematicamente vence a briga por vaga contra notícias, que
sempre têm `engagement = 0`. Resultado observado em produção: 40 itens, sendo
25 Reddit, 13 YouTube, **0 notícias**.

Objetivo: garantir cobertura mínima por tipo de conteúdo (sem inventar item
fictício se não existir candidato suficiente), aumentar o total de itens
mantidos, e ampliar a busca de notícias pra outros idiomas — sem nunca exibir
conteúdo em outro idioma que não português no site.

## Cotas protegidas

- `MAX_ITEMS`: 40 → **60**.
- Cotas novas (protegidas da expulsão no corte, pegando os de maior `signal`
  disponíveis daquele tipo, até o número — nunca força a existir mais do que
  realmente há candidatos):
  - `MIN_NEWS = 10`
  - `MIN_VIDEO_LONGO = 10`
  - `MIN_VIDEO_CURTO = 10`
- Reddit **sem cota fixa** — preenche o restante do espaço (~30 vagas)
  naturalmente, já que é a fonte mais prolífica.
- A proteção por categoria já existente (lançamento/trabalhista/vendas com
  `signal >= 5`) continua em paralelo, somando-se às cotas de tipo — um item
  pode ser protegido por qualquer uma das regras.

## Notícias em PT/EN/ES

`fetch_news()` passa a buscar em três idiomas/regiões via Google News RSS,
cada um com sua própria lista de termos de busca (não é tradução literal —
termos como "vazamento"/"leak"/"filtración" precisam de equivalente local
pra pegar cobertura regional de verdade):

- **Português** (`hl=pt-BR&gl=BR&ceid=BR:pt-419`) — mantém as queries atuais.
- **Inglês** (`hl=en-US&gl=US&ceid=US:en`) — cobre imprensa como IGN, Polygon,
  Kotaku etc.
- **Espanhol** (`hl=es-419&gl=MX&ceid=MX:es-419`) — cobre imprensa hispânica.

Cada item de notícia ganha um campo interno `newsLang` (`"pt"|"en"|"es"`),
indicando a busca de origem — usado só internamente (não vai pro `data.json`
final), pra decisão de idioma abaixo.

## Regra de idioma no resultado final

**O headline/descrição/gancho exibidos no site precisam sempre estar em
português.** Hoje a tradução acontece via reescrita por IA (Claude/Gemini),
que já traduz tudo pro tom do canal em PT-BR — mas essa reescrita é
best-effort: se a chave não estiver configurada, ou a chamada falhar (já
vimos isso acontecer nesta sessão, um timeout do Gemini), o item cai no modo
template cru, no idioma original.

Regra: depois da tentativa de reescrita em `build_items()`, se `rewritten`
vier vazio/falso (reescrita não aconteceu nessa rodada, por qualquer motivo),
**qualquer item de notícia com `newsLang != "pt"` é descartado daquela
rodada** — não entra no `data.json`. Segue a mesma filosofia já usada no
resumo diário: silêncio é melhor que exibir errado. Como o Gemini já está
configurado em produção, isso deve ser raro na prática — só afeta rodadas
onde a reescrita falhar ou (hipoteticamente) rodar sem nenhuma chave de IA.

Itens de notícia em português (`newsLang == "pt"`) nunca são descartados por
essa regra, com ou sem reescrita — já estão no idioma certo.

## Arquivos afetados

- `scripts/fetch_signals.py` — `fetch_news()` ganha loop multi-idioma;
  `build_items()`/`main()` ganham a lógica de cotas protegidas e o filtro de
  idioma pós-reescrita. Nenhum arquivo novo, é extensão do que já existe.

## Isolamento e rollout

Mesmo padrão já estabelecido: construído e validado no repositório de teste
(`vigia-gta6-test`) primeiro. Só porta pra `vigia-gta6-site` com aprovação
explícita do usuário.
