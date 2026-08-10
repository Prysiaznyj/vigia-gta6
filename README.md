# VIGIA // GTA VI — site automático

Site estático que mostra sinais em alta sobre GTA 6 (notícias, Reddit, YouTube). Um robô roda sozinho a
cada 4h via GitHub Actions, atualiza `data.json`, e o site lê esse arquivo. Ninguém precisa pedir pra
rodar nada — é só abrir o link.

## O que dá pra automatizar de graça e o que não dá

- **Notícias** (Google News RSS) — automático, sem chave.
- **Reddit** (r/GTA6) — automático, sem chave.
- **YouTube** — automático, mas precisa de uma API key gratuita do Google (2 min pra criar).
- **X/Twitter** — a API oficial de busca não tem mais plano gratuito viável (fica na faixa de
  US$100+/mês). Não entrou no v1. Se topar pagar, dá pra plugar depois.
- **TikTok** — não existe API pública de busca/trending confiável. Não entrou no v1.
- **Reescrita no tom do canal** (headline/desc/hook mais afiados, no estilo que eu escrevi à mão) —
  opcional, usa a API da Anthropic se você configurar a chave. Sem ela, o robô usa um gancho por
  template (mais cru, mas funciona).

## Opção rápida: `setup.sh`

Faz tudo abaixo num comando só — cria o repo, sobe os arquivos, ativa o Pages, configura as
secrets e dispara a primeira varredura. Precisa do `gh` CLI instalado (github.com/cli/cli) e
rodar num terminal com internet de verdade (Git Bash/WSL no Windows, ou peça pro Claude Code
rodar isso pra você — o sandbox do Cowork não tem acesso ao GitHub, então essa parte não dá
pra automatizar por ali).

```bash
cd vigia-gta6-site
export YOUTUBE_API_KEY="..."      # opcional
export ANTHROPIC_API_KEY="..."    # opcional
./setup.sh vigia-gta6 public
```

Se não estiver logado no `gh`, o script pede `gh auth login` (abre o navegador, um clique).

## Setup manual (se preferir passo a passo, ~10 minutos)

1. **Crie um repositório no GitHub** (gratuito): github.com → New repository → nome
   `vigia-gta6` (ou o que quiser) → público ou privado, tanto faz.
2. **Suba estes arquivos pra raiz do repositório** (não dentro de uma subpasta):
   `index.html`, `data.json`, `requirements.txt`, `README.md`, a pasta `scripts/` e a pasta
   `.github/`.
3. **Ative o GitHub Pages**: Settings → Pages → Source: "Deploy from a branch" → branch `main`,
   pasta `/ (root)` → Save. Em 1-2 min o site fica no ar em
   `https://seu-usuario.github.io/vigia-gta6/`.
4. **(Opcional, recomendado) YouTube API key**: console.cloud.google.com → crie um projeto →
   ative "YouTube Data API v3" → Credentials → Create API Key. Depois, no repositório:
   Settings → Secrets and variables → Actions → New repository secret →
   nome `YOUTUBE_API_KEY`, valor a chave.
5. **(Opcional) Anthropic API key**, pra reescrita no tom do canal: console.anthropic.com →
   gere uma chave → mesmo caminho acima, secret `ANTHROPIC_API_KEY`. Isso gasta uns centavos de
   crédito a cada varredura (é uma chamada de API paga por uso, não sua assinatura do Claude).
6. **Teste na hora**: aba Actions do repositório → "Varredura VIGIA GTA VI" → Run workflow.
   Depois de rodar, dá refresh no site e confere se os cards mudaram.

Pronto. Dali em diante roda sozinho a cada 4h, para sempre, sem precisar pedir nada.

## Ajustar a frequência

Em `.github/workflows/sweep.yml`, troque `cron: "0 */4 * * *"` — por exemplo `0 */6 * * *` pra
de 6 em 6h, ou `0 * * * *` pra de hora em hora (mais chamadas de API, mais chance de bater limite
grátis do Reddit/YouTube).

## Estrutura

```
index.html              → site (lê data.json, não precisa editar)
data.json                → dados atuais, reescrito pelo robô a cada rodada
requirements.txt         → dependências Python do robô
scripts/fetch_signals.py → o robô: busca, classifica, pontua, escreve data.json
.github/workflows/sweep.yml → agenda do robô (GitHub Actions)
```
