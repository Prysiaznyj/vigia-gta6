# Resumo diário (Notion + Telegram) — design

**Data:** 2026-08-10

## Contexto e objetivo

O VIGIA já coleta e pontua sinais (0-5, campo `signal`) a cada 4h em `data.json`. O
volume acumulado (até 40 itens) é bom pra explorar no site, mas ruim pra decisão
rápida: a pessoa que vai gravar conteúdo não deve ter que abrir o site e escolher
entre dezenas de opções todo dia — isso trava, não move.

Objetivo: 1x por dia, selecionar só os sinais realmente fortes das últimas 24h e
**empurrar** isso pra pessoa (Telegram, que ela vê sem precisar lembrar de abrir
nada) e **arquivar** num lugar buscável (Notion, pra consultar depois "o que rendeu
semana passada").

**Fora de escopo aqui:** uma forma de configuração "sem código" pra comprador não-
técnico de outro nicho (ex: um formulário na própria página) esbarra em o site ser
100% estático (GitHub Pages, sem backend) — não dá pra gravar secret do GitHub
direto de uma página client-side sem adicionar infraestrutura própria (contra o
objetivo de manter grátis/barato). Fica como iniciativa futura, junto da discussão
maior de generalizar a ferramenta pra outros nichos.

## Seleção diária

Rodando 1x/dia, a partir do `data.json` já existente:

1. Filtra itens com `publishedAt` dentro das últimas 24h corridas **e** `signal >= 4`.
2. Ordena por `signal` desc, desempate por `publishedAt` mais recente.
3. Pega os 3 primeiros.
4. Remove quem já estiver registrado em `digest_sent.json` (evita duplicar caso o
   mesmo item ainda esteja dentro da janela de 24h no dia seguinte).
5. Se sobrar 0 itens após os filtros: **não envia nada** — nem Notion, nem Telegram.
   Silêncio é preferível a mandar item fraco só pra completar número.

## Timing

Workflow novo e separado (não mexe no `sweep.yml` existente): cron `30 0 * * *`
(00:30 UTC = ~21h30 de Brasília), mais `workflow_dispatch` pra disparo manual/teste.
O horário é deslocado 30 minutos do tick `0 0 * * *` compartilhado com o
`sweep.yml` (que roda a cada 4h) especificamente pra evitar que os dois
workflows disputem o mesmo `git push` na mesma janela e um deles seja
rejeitado por non-fast-forward.

## Notion

Uma linha nova por item selecionado, numa database já existente (criada manualmente
pelo usuário, compartilhada com a integração antes do primeiro uso) com estas
colunas/propriedades exatas:

| Propriedade | Tipo Notion |
|---|---|
| Headline   | title |
| Categoria  | select |
| Sinal      | number |
| Data       | date |
| Gancho     | rich_text |
| Link       | url |

Escrita via `POST https://api.notion.com/v1/pages` (header `Notion-Version:
2022-06-28`), `parent.database_id` = `NOTION_DATABASE_ID`, uma chamada por item.

## Telegram

Uma única mensagem (não uma por item), formatada em HTML (`parse_mode=HTML` —
evita ter que escapar caracteres especiais que apareçam em headlines reais, ao
contrário do MarkdownV2), numerada 1-3 por ordem de sinal, cada item com headline
em negrito, o gancho, e o link.

`TELEGRAM_CHAT_ID` aceita uma lista separada por vírgula — a mensagem é enviada
(uma chamada `POST /sendMessage` por destinatário) pra cada ID da lista, permitindo
múltiplas pessoas recebendo o mesmo resumo a partir do mesmo bot. Cada destinatário
precisa ter iniciado conversa com o bot (`/start`) pelo menos uma vez antes —
restrição do próprio Telegram contra spam.

## Credenciais

Todas opcionais (secrets do GitHub, mesmo padrão de `YOUTUBE_API_KEY` etc.):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`.

- Sem nenhuma configurada: o script sai sem erro, sem fazer nada.
- Só Telegram configurado: escreve só no Telegram, pula Notion.
- Só Notion configurado: escreve só no Notion, pula Telegram.

`setup.sh` ganha um modo guiado pra essas 4 variáveis: pergunta uma de cada vez,
com instrução de onde conseguir cada uma (ex: "abra t.me/BotFather, mande /newbot,
cole o token aqui"), e configura os secrets — mais fácil que navegar manualmente
pelas configurações do GitHub, mesmo ainda sendo um passo de terminal.

## Arquivos novos

- `scripts/daily_digest.py` — lê `data.json`, seleciona, escreve Notion/Telegram,
  atualiza `digest_sent.json`. Não importa nem modifica `fetch_signals.py`.
- `.github/workflows/digest.yml` — cron diário + `workflow_dispatch`.
- `digest_sent.json` — controle de itens já enviados (por `url`), commitado pelo
  workflow como os outros arquivos de estado. Prunado (remove entradas com mais de
  ~3 dias) pra não crescer sem limite.
- `setup.sh` — modo guiado adicional pras 4 credenciais novas.

## Tratamento de erro

Mesmo padrão já estabelecido no projeto: cada chamada externa (Notion, Telegram)
em try/except próprio, loga em stderr, segue em frente — uma falhando não impede a
outra. `digest_sent.json` corrompido/ilegível é tratado como o `channel_baselines.json`
(não trava, começa do zero).

## Isolamento e rollout

Construído e validado primeiro no repositório de teste (`vigia-gta6-test`), do
mesmo jeito que a feature de outlier — o usuário confirmou que quer sempre testar
antes de ir pra produção. Só porta pra `vigia-gta6-site` depois de aprovação
explícita.
