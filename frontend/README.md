# BioCurate frontend

The React app talks to the Co-Scientist API. It submits the research question and
any selected files to `POST /api/sessions`, then reads progress, hypotheses and
the final synthesis from that session. It does not include sample research data.

## Run locally

Start the backend from the repository root in one terminal:

```bash
source .venv/bin/activate
co-scientist serve
```

The API listens on `http://127.0.0.1:7878`. Configure a model provider first as
described in the root [quickstart](../README.md#quickstart), then run
`co-scientist init` and `co-scientist doctor` if this is a new checkout.

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). The Vite dev server
proxies `/api` and `/healthz` to the backend on port 7878. Upload supported
research files in the composer; the backend validates configured attachment
limits and reports any intake errors in the UI. Supported formats are PDF,
DOCX, CSV, TXT and ZIP archives of supported files.

See [the frontend API guide](../docs/frontend-api.md) for endpoint and data
details.
