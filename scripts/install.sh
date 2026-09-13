#!/usr/bin/env bash
set -euo pipefail

auto_confirm=false
client_flags=()

usage() {
  printf '%s\n' "Usage: scripts/install.sh [--yes] [--client CLIENT]" \
    "       scripts/install.sh [--claude] [--codex] [--kimi] [--antigravity]" \
    "" \
    "Installs the tracekite CLI and selected global skill files." \
    "MCP server registration remains an explicit per-client step."
}

add_client() {
  case "$1" in
    all|claude|codex|kimi|antigravity)
      client_flags+=("--client" "$1")
      ;;
    *)
      printf 'Unsupported client: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      auto_confirm=true
      shift
      ;;
    --claude|--codex|--kimi|--antigravity)
      add_client "${1#--}"
      shift
      ;;
    --gemini)
      add_client "antigravity"
      shift
      ;;
    -c|--client)
      if [[ $# -lt 2 ]]; then
        printf '%s requires a value\n' "$1" >&2
        exit 2
      fi
      add_client "$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv is required. Install uv, then rerun this script." >&2
  exit 1
fi

printf '%s\n' \
  "TraceKite setup will:" \
  "  - Install the tracekite CLI as a uv tool." \
  "  - Install the selected global TraceKite skill files." \
  "  - Leave existing skill files and all MCP client configuration untouched."

if [[ "$auto_confirm" == false ]]; then
  read -r -p "Proceed? [Y/n] " response
  case "$response" in
    ""|y|Y|yes|YES|Yes) ;;
    [0-9]*)
      printf '%s\n' "This is not a menu: type Y to proceed or n to cancel." >&2
      printf '%s\n' "Installation cancelled."
      exit 0
      ;;
    *) printf '%s\n' "Installation cancelled."; exit 0 ;;
  esac
fi

cd "$repo_root"
uv tool install --no-cache --force .

# ${arr[@]+...} because bash 3.2 (macOS /bin/bash) treats an empty "${arr[@]}"
# as an unbound variable under set -u.
if command -v tracekite >/dev/null 2>&1; then
  tracekite install-skill ${client_flags[@]+"${client_flags[@]}"}
else
  uv tool run --from "$repo_root" tracekite install-skill ${client_flags[@]+"${client_flags[@]}"}
fi

printf '%s\n' \
  "" \
  "TraceKite CLI and skills are ready." \
  "Register the MCP server for each client using the commands in:" \
  "  docs/plugins-and-mcp-guide.md" \
  "" \
  "Verify: tracekite --help" \
  "Serve:  tracekite mcp /absolute/path/to/repo-a /absolute/path/to/repo-b"
