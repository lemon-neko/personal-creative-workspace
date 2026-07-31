# Project guidance

This repository contains a local-first FastAPI personal idea workspace.

- Keep user content in `content/items/*.md`; do not introduce a database.
- Only `published` content may render under `/garden`.
- Trash must remain recoverable until explicit permanent-delete confirmation.
- Raw Markdown HTML stays disabled. Treat model output as untrusted Markdown.
- Model integration must remain optional and OpenAI-compatible through environment variables.
- Never overwrite a source item when saving a polished article; create a child item with `parent_id`.
- Keep all author routes local-only until authentication is introduced.
