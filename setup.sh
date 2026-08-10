#!/usr/bin/env bash
# Setup automático do VIGIA GTA VI: cria o repo no GitHub, sobe os arquivos,
# ativa o Pages, configura secrets (se fornecidas) e dispara a primeira varredura.
#
# Rodar de dentro desta pasta (vigia-gta6-site/), num terminal com internet de verdade
# (Git Bash, WSL ou terminal do Claude Code no seu computador — não funciona no sandbox do Cowork).
#
# Uso:
#   ./setup.sh [nome-do-repo] [public|private]
#
# Opcional, antes de rodar, pra já deixar as chaves configuradas:
#   export YOUTUBE_API_KEY="..."
#   export ANTHROPIC_API_KEY="..."
#   ./setup.sh

set -euo pipefail

REPO_NAME="${1:-vigia-gta6}"
VISIBILITY="${2:-public}"

command -v gh >/dev/null 2>&1 || {
  echo "gh CLI não encontrado."
  echo "Instale: https://cli.github.com/  (Windows: winget install GitHub.cli | Mac: brew install gh)"
  exit 1
}

if ! gh auth status >/dev/null 2>&1; then
  echo "Você ainda não está logado no GitHub CLI. Rodando 'gh auth login'..."
  gh auth login
fi

cd "$(dirname "$0")"

if [ ! -d .git ]; then
  git init -b main
  git add .
  git commit -m "vigia gta6: setup inicial" >/dev/null
  echo "Repo git local criado."
fi

if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
  echo "Repo $REPO_NAME já existe no GitHub, só vou garantir que o remote está certo e dar push."
  OWNER=$(gh api user --jq .login)
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  git push -u origin main
else
  gh repo create "$REPO_NAME" --"$VISIBILITY" --source=. --remote=origin --push
  echo "Repo $REPO_NAME criado e código enviado."
fi

OWNER=$(gh api user --jq .login)

if gh api "repos/$OWNER/$REPO_NAME/pages" >/dev/null 2>&1; then
  echo "GitHub Pages já estava ativo."
else
  gh api -X POST "repos/$OWNER/$REPO_NAME/pages" -f "source[branch]=main" -f "source[path]=/" >/dev/null
  echo "GitHub Pages ativado."
fi

if [ -n "${YOUTUBE_API_KEY:-}" ]; then
  gh secret set YOUTUBE_API_KEY --body "$YOUTUBE_API_KEY" --repo "$OWNER/$REPO_NAME"
  echo "Secret YOUTUBE_API_KEY configurada."
else
  echo "Sem YOUTUBE_API_KEY no ambiente — pulei esse secret (o robô roda sem YouTube até você configurar)."
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  gh secret set ANTHROPIC_API_KEY --body "$ANTHROPIC_API_KEY" --repo "$OWNER/$REPO_NAME"
  echo "Secret ANTHROPIC_API_KEY configurada."
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  gh secret set GEMINI_API_KEY --body "$GEMINI_API_KEY" --repo "$OWNER/$REPO_NAME"
  echo "Secret GEMINI_API_KEY configurada (free tier do Gemini)."
else
  echo "Sem ANTHROPIC_API_KEY nem GEMINI_API_KEY no ambiente — pulei (ganchos ficam no modo template, de graça)."
fi

sleep 3
gh workflow run sweep.yml --repo "$OWNER/$REPO_NAME" 2>/dev/null \
  && echo "Primeira varredura disparada." \
  || echo "Workflow ainda não indexado pelo GitHub — espera ~1 min e roda: gh workflow run sweep.yml --repo $OWNER/$REPO_NAME"

echo ""
echo "Feito. Site (pode levar 1-2 min pra publicar pela primeira vez):"
echo "https://$OWNER.github.io/$REPO_NAME/"
