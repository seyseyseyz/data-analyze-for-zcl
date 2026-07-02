#!/usr/bin/env bash

is_compatible_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

select_xhs_ca_python() {
  local home_dir="${HOME:-/nonexistent}"
  local candidate
  local resolved
  local candidates

  if [[ -n "${XHS_CA_PYTHON:-}" ]]; then
    if [[ ! -x "$XHS_CA_PYTHON" ]]; then
      echo "XHS_CA_PYTHON is set but is not executable: $XHS_CA_PYTHON" >&2
      return 2
    fi
    if ! is_compatible_python "$XHS_CA_PYTHON"; then
      echo "XHS_CA_PYTHON must point to Python 3.11 or newer: $XHS_CA_PYTHON" >&2
      return 2
    fi
    printf '%s\n' "$XHS_CA_PYTHON"
    return 0
  fi

  if [[ -n "${XHS_CA_PYTHON_CANDIDATES:-}" ]]; then
    # shellcheck disable=SC2206
    candidates=($XHS_CA_PYTHON_CANDIDATES)
  else
    candidates=(python3.12 python3.11 python3 "$home_dir/.local/bin/python3.12" "$home_dir/.local/bin/python3.11" /usr/local/bin/python3.12 /usr/local/bin/python3.11 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 "$home_dir/.pyenv/shims/python3.12" "$home_dir/.pyenv/shims/python3.11")
  fi

  for candidate in "${candidates[@]}"; do
    if [[ "$candidate" = */* ]]; then
      [[ -x "$candidate" ]] || continue
      resolved="$candidate"
    elif command -v "$candidate" >/dev/null 2>&1; then
      resolved="$(command -v "$candidate")"
    else
      continue
    fi
    if is_compatible_python "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done

  return 1
}
