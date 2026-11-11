# DUSC Action Board — site

Netlify deploys this branch. `site/` is the page, `netlify/functions/api.mjs` is the passcode sign-in
and data proxy. The board's data lives on the `main` branch under `data/`.

Netlify environment variables: `BOARD_PASSCODE` (8+ characters), `GITHUB_TOKEN` (fine-grained,
Contents read/write on this repo only).
