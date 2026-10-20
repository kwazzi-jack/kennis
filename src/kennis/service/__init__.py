"""The kennis service: one process per corpus, and every front end its client.

Milestone 14. It owns the corpus while it runs: every write is a job in a
lane, waiting its turn rather than being refused, and every read is
answered from a process that already holds the index and the model. The
window's pages are served by it, and the command line and the MCP server
reach it over loopback with a token.
"""
