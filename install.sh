#!/bin/sh
# Graveyard Shift installer:  curl -fsSL https://mohamedaminehamdi.github.io/graveyard-shift/install.sh | sh
#
# Everything goes in your home folder; no admin password. It installs:
#   uv (runs the app's Python), Graveyard Shift, Ollama + Gemma 4 (the ghosts), TabPFN's open weights (learns when you
#   wake), the open-source Temporal server (keeps the night alive through crashes), and an app in ~/Applications.
# Nothing is ever sent: no ghost can send mail, accept invites, move files or push code.
# Undo it all: graveyard-shift --uninstall && uv tool uninstall graveyard-shift
set -eu

SITE="https://mohamedaminehamdi.github.io/graveyard-shift"
WHEEL="${GS_SOURCE:-$SITE/graveyard_shift-0.1.0-py3-none-any.whl}"

say() { printf '\n\033[1m👻 %s\033[0m\n' "$1"; }
fail() { printf '\n%s\n' "$1" >&2; exit 1; }

main() {
  [ "$(uname -s)" = Darwin ] || fail "Graveyard Shift is for macOS."
  [ "$(uname -m)" = arm64 ] || fail "Graveyard Shift needs a Mac with Apple silicon (M1 or newer)."
  [ "$(sw_vers -productVersion | cut -d. -f1)" -ge 14 ] || fail "Graveyard Shift needs macOS 14 (Sonoma) or newer."

  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv, which runs Graveyard Shift's Python without touching your system"
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi

  say "Installing Graveyard Shift"
  uv tool install --force --refresh --python 3.12 "$WHEEL" </dev/null
  bin="$(uv tool dir --bin)"

  flags=""
  if [ -n "${GS_SKIP_MODELS:-}" ]; then
    flags="--skip-models"
  elif ! curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
    if [ -d /Applications/Ollama.app ] || [ -d "$HOME/Applications/Ollama.app" ]; then
      say "Starting Ollama"
      open -g -a Ollama </dev/null || true
    else
      say "Installing Ollama, which runs Gemma 4 on this Mac"
      tmp="$(mktemp -d)"
      curl -fL --progress-bar https://ollama.com/download/Ollama-darwin.zip -o "$tmp/Ollama.zip"
      mkdir -p "$HOME/Applications"
      ditto -xk "$tmp/Ollama.zip" "$HOME/Applications"
      rm -rf "$tmp"
      open -g "$HOME/Applications/Ollama.app" </dev/null || true
    fi
  fi

  answer=n
  if [ -z "${GS_SKIP_MODELS:-}" ] && (: </dev/tty) 2>/dev/null; then
    printf '\nLet the ghosts rise every night after you fall asleep? (Leave the Mac open and plugged in.) [y/N] '
    read -r answer </dev/tty || answer=n
  fi
  case "$answer" in [yY]*) flags="$flags --every-night" ;; esac

  say "Downloading the models and making the app"
  # shellcheck disable=SC2086  # $flags is a list of words
  "$bin/graveyard-shift" --setup $flags </dev/null

  say "All set. Graveyard Shift is in your Applications folder."
  if [ -z "${GS_SKIP_MODELS:-}" ]; then
    echo "Opening it now. Leave the ghosts a note at bedtime and say Goodnight."
    open "$HOME/Applications/Graveyard Shift.app"
  fi
}

main "$@"
