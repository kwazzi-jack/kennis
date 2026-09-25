# Refuse any non-ASCII byte in a file kennis tracks. The project rule is ASCII
# everywhere: no em dashes, arrows, curly quotes or middle dots. Use `-`, `->`,
# `:` and straight quotes instead.
#
# `-r` so the same script serves pre-commit, which passes changed files one by
# one, and CI, which passes directories. `-I` with it, because a recursive
# walk reaches compiled bytecode and a `.pyc` is full of bytes above 127 -
# without it the check fails on every directory that has ever been imported.
#
# The guard matters: `grep` with no file arguments reads standard input, which
# in CI is empty, so it finds nothing and the check passes without having
# looked at anything. Exiting early makes "nothing to check" say so.
if [ "$#" -eq 0 ]; then
    echo "check_ascii: nothing to check" >&2
    exit 0
fi
if grep -rInP --exclude-dir=__pycache__ '[^\x00-\x7F]' "$@"; then
    echo "error: non-ASCII bytes above" >&2
    exit 1
fi
exit 0
