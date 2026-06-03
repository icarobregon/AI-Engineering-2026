#!/usr/bin/env bash
# PreToolUse Bash hook: bloquea merges/push que llevarían una rama
# session_NN_* a main durante el máster LIDR AI Engineering 2026/05.
#
# Recibe JSON por stdin (hook input). Lee `tool_input.command`.
# Exit 0 = permite. Exit 2 = bloquea (stderr se muestra al modelo y al usuario).

set -euo pipefail

cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
[ -z "$cmd" ] && exit 0

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

block=0
reason=""

# 1) `git merge` referenciando una rama session_NN_* en cualquier argumento
if printf '%s' "$cmd" | grep -qE '\bgit[[:space:]]+merge\b.*\bsession_[0-9]+'; then
    block=1
    reason="git merge contra una rama session_NN_*"
fi

# 2) `gh pr merge` con --base main + algo que mencione session_NN_*
if printf '%s' "$cmd" | grep -qE '\bgh[[:space:]]+pr[[:space:]]+merge\b' \
   && printf '%s' "$cmd" | grep -qE '\-\-base[[:space:]]+main\b' \
   && printf '%s' "$cmd" | grep -qE 'session_[0-9]+'; then
    block=1
    reason="gh pr merge con --base main desde session_NN_*"
fi

# 3) `gh pr merge` ejecutado mientras estamos en una rama session_NN_*
#    (por defecto gh toma el PR de la rama actual)
if printf '%s' "$cmd" | grep -qE '\bgh[[:space:]]+pr[[:space:]]+merge\b' \
   && printf '%s' "$branch" | grep -qE '^session_[0-9]+'; then
    block=1
    reason="gh pr merge desde la rama actual $branch (session_NN_*)"
fi

# 4) `git push` que reescriba main desde un ref session_NN_*
#    Cubre: `git push origin session_X:main`, `git push origin +session_X:main`,
#           `git push -f origin session_X:refs/heads/main`, etc.
if printf '%s' "$cmd" | grep -qE '\bgit[[:space:]]+push\b.*session_[0-9]+[^[:space:]]*:[^[:space:]]*main\b'; then
    block=1
    reason="git push reescribiendo main desde session_NN_*"
fi

if [ "$block" -eq 1 ]; then
    cat >&2 <<EOF
BLOQUEADO: estás intentando $reason en el repo del máster LIDR.

Durante el máster, las ramas session_NN_* NO deben mergearse a main hasta
sesión 17 (final del programa). Ver:
  - CLAUDE.md, sección "Branching and folder layout"
  - memoria feedback-session-branch-workflow

Comando interceptado:
  $cmd

Si realmente quieres saltarte la regla (caso excepcional o final del
programa), confirma con Claude. Para desactivar el hook temporalmente:
edita .claude/settings.json o renombra este script.
EOF
    exit 2
fi

exit 0
