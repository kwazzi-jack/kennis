# Refuse a silenced type error. The project rule is that types are fixed, not
# suppressed: a `# type: ignore` is a mypy finding that stops being reported
# without stopping being true. Narrow with `isinstance`, change the signature,
# or reach for the library's documented interface instead.
#
# Only Python files reach here, so this script cannot match its own text.
if grep -nE '#\s*type:\s*ignore' "$@"; then
    echo "error: silenced type errors above; fix the type instead" >&2
    exit 1
fi
exit 0
