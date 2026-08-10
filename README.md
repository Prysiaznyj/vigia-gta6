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
  três modos, o robô tenta nessa ordem:
  1. `ANTHROPIC_API_KEY` configurada → usa a API da Anthropic (paga por uso, a melhor qualidade).
  2. Sem ela, mas com `GEMINI_API_KEY` configurada → usa o **free tier do Gemini**
     (gemini-2.5-flash), de graça, sem cartão de crédito, dá conta tranquilo do volume de uma
     varredura a cada 4h. É a opção recomendada se quiser ficar de graça sem ficar no modo cru.
     Gere a chave em aistudio.google.com/apikey (é só logar com conta Google).
  3. Sem nenhuma das duas → modo template, cru mas de graça e sem configurar nada (é o que está
     rodando agora).
- **Cada implantação usa a própria chave.** Isso não é uma chave central minha nem sua compartilhada
  — é uma secret configurada NO REPOSITÓRIO do GitHub de quem estiver rodando aquela cópia. Se
  outra pessoa clonar esse projeto pro canal dela, ela cria a conta dela na Anthropic/Google, gera
  a própria chave e configura como secret no repo dela. Não tem custo nem acesso cruzado entre
  implantações diferentes.

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
5. **(Opcional) Reescrita no tom do canal** — escolha uma:
   - Anthropic (paga por uso, melhor qualidade): console.anthropic.com → gere uma chave →
     secret `ANTHROPIC_API_KEY`.
   - Gemini (de graça, free tier): aistudio.google.com/apikey → gere uma chave → secret
     `GEMINI_API_KEY`. Nenhuma cobrança dentro dos limites do free tier.
   Sem nenhuma das duas, fica no modo template — de graça, mais cru.
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
