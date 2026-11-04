# Bombometro

Read the Borant conventions before changing routes, styling, authentication or
languages: `wiki/projects/strumenti/convenzioni-tool-borant.md` in Ono3, or
Onopedia `get_page("convenzioni-tool-borant")`. Do not duplicate that document.
The private detailed authentication specification is `borant-id/SPEC.md` §20.

This preview uses FastAPI/Jinja, behind an external lab login, without application
accounts. Do not expose it publicly. `SPEC.md` is local and gitignored; a fresh
clone does not include it. See README.md and DEPLOY.md for the delivered scope.
Keep code, comments, documentation and commits in English. Preserve core.py scoring
unless a separate change explicitly documents and tests new domain behaviour.
