# Bombometro

Read the Borant conventions before changing routes, styling, authentication or
languages: `wiki/projects/strumenti/convenzioni-tool-borant.md` in Ono3, or
Onopedia `get_page("convenzioni-tool-borant")`. Do not duplicate that document.
The private detailed authentication specification is `borant-id/SPEC.md` §20.

This app uses FastAPI/Jinja without application accounts. Default lab mode runs
behind an external lab login. On 5 November 2026 the owner chose anonymous public
deployment: use the explicit public mode and follow DEPLOY.md, not a direct public
bind of the workshop process. `SPEC.md` is local and gitignored; a fresh
clone does not include it. See README.md and DEPLOY.md for the delivered scope.
Keep code, comments, documentation and commits in English. Preserve core.py scoring
unless a separate change explicitly documents and tests new domain behaviour.
