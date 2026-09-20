# Refuse any non-ASCII byte in a file kennis tracks. The project rule is ASCII
# everywhere: no em dashes, arrows, curly quotes or middle dots. Use `-`, `->`,
# `:` and straight quotes instead.
if grep -nP '[^\x00-\x7F]' "$@"; then
    echo "error: non-ASCII bytes above" >&2
    exit 1
fi
exit 0
