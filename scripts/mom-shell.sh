# bash / zsh: source this file AFTER placing the installed `m2` executable on PATH.
# Remove an existing `alias m2` first. `command m2` bypasses this function.
function m2() {
    local mom_file mom_code mom_target
    mom_file="$(mktemp "${TMPDIR:-/tmp}/mom-last.XXXXXXXX")" || return 1
    command m2 "$@" --last-dir-file "$mom_file"
    mom_code=$?
    if [[ $mom_code -eq 0 && -s "$mom_file" ]]; then
        # Read until EOF rather than newline, preserving newline-containing paths.
        IFS= read -r -d '' mom_target < "$mom_file" || true
        if [[ -n "$mom_target" && -d "$mom_target" ]]; then
            builtin cd -- "$mom_target" || mom_code=$?
        fi
    fi
    command rm -f -- "$mom_file"
    return "$mom_code"
}
