# Demo script: 3-minute shot list

Pitch: an AI co-scientist with traceable evidence, built on MongoDB Atlas.

Shots marked **[NEEDS SESSION]** require a completed `co-scientist run` on the
Atlas backend (this bills the configured LLM provider; run it once before filming).
The 0:00-0:55 rows (pitch, ingest and stats, library search) and the `library` collection and index views in the 1:50-2:25 row only need the ingested library and can be filmed now.

Setup before filming: `[storage] backend = "atlas"` in the config, `MONGODB_URI`
and `VOYAGE_API_KEY` in `.env` (keep `.env` and the Atlas connection string off
screen; blur the Atlas "Connect" dialog). Terminal font large, dark theme.

Goal used throughout: `Identify hypotheses about TREM2 and microglial dysfunction in Alzheimer's disease`

## Shot list

| Time | On screen | Voice-over |
| --- | --- | --- |
| 0:00-0:15 | Title card, then the README "Built on MongoDB Atlas" diagram. | "Scientific ideas are cheap. Evidence you can check is not. This is an open source version of Google's AI co-scientist, rebuilt so that every claim points to a passage in a paper, and MongoDB Atlas is the store underneath." |
| 0:15-0:35 | Terminal: `co-scientist library ingest "TREM2 microglia Alzheimer" --max-papers 15`, then `co-scientist library stats`. Highlight `index library_text: status=READY queryable=True` and `index library_vec: status=READY queryable=True`. (If recording live, cut the wait; the autoEmbed index took about 90 s to build.) | "First we build an evidence library. Europe PMC open-access full text is split into passages with stable anchors, paragraphs, figure captions, tables, and stored in one Atlas collection. Two indexes sit on it: Atlas Search for keywords, and an Automated Embedding vector index, where Atlas itself embeds every passage with Voyage. We send no vectors." |
| 0:35-0:55 | Terminal: `co-scientist library search "TREM2 and amyloid plaque compaction" --k 5`. Point at the `anchor_id` column (`PMC…#F2`), the `fused` column and the `rerank` column. | "Search is hybrid. One aggregation, dollar-rankFusion, merges the keyword and vector results, and Voyage rerank-2.5 reorders them. Each hit carries its anchor, so a figure caption is as citable as a paragraph." |
| 0:55-1:10 | Terminal: `co-scientist run "<goal>" --n 3 --budget-usd 2.0 --wall-clock 600` started; cut to a second terminal with `co-scientist serve` and the browser at `http://localhost:7878`. **[NEEDS SESSION]** (start the run live, then show a finished session on the dashboard for the rest). | "Now the co-scientist runs. Generation, Reflection, Ranking, Evolution and Meta-review work from a task queue in Atlas. Agents get a search_library tool and are told to cite the anchor." |
| 1:10-1:25 | Dashboard session page: leaderboard with Elo, event stream. **[NEEDS SESSION]** | "Hypotheses are ranked by an Elo tournament of head-to-head debates. The dashboard streams events straight from Atlas." |
| 1:25-1:50 | Dashboard, open the top hypothesis detail page, scroll to **Citations**. Zoom on a URL ending in `#F2` (a figure) or `#s2.p3`. Click it: Europe PMC opens at that passage. **[NEEDS SESSION]** | "The top hypothesis cites a figure caption, not just a paper. The link is a Europe PMC URL with the anchor fragment, so a reviewer lands on the exact passage the agent saw. An agent can only cite a URL it actually retrieved." |
| 1:50-2:25 | **[NEEDS SESSION]** except the `library` collection and the index views, which need only the ingested library. Atlas UI (browser): Data Explorer on db `biocurate`, collections `library`, `hypotheses`, `hypothesis_vectors`, `elo_journal`, `tasks`, `events`. Then Atlas Search tab: indexes `library_text`, `library_vec` (type autoEmbed), `hyp_vec`, all Active. Then the Aggregation builder on `library`: paste the `$rankFusion` stage (`pipelines.text` = `$search` on `library_text`, `pipelines.vector` = `$vectorSearch` on `library_vec`) and show the output. (The pipeline is built by `build_hybrid_pipeline` in `co_scientist/library/search.py`.) | "In Atlas: the library, the hypotheses, their vectors and the tournament journal live side by side. Three search indexes: lexical, automated embedding, and a vector index for deduplicating hypotheses. And this is the whole hybrid retrieval: a single rankFusion pipeline." |
| 2:25-2:45 | Data Explorer, `elo_journal`: open a document (`match_id`, `elo_a_before`, `elo_a_after`, ...). Then the terminal or `hypothesis_vectors` collection. **[NEEDS SESSION]** Note: duplicate detection logs nothing on a hit, so show it instead with `pytest -q co_scientist/tests/atlas -k vector` (CO_SCI_ATLAS_TESTS=1) or the earlier measured values: cosine 0.989 for a near-duplicate (flagged at 0.92) versus 0.684 for an unrelated hypothesis. | "Every rating change is one multi-document transaction: a journal entry keyed by the match id and both hypotheses updated together, so a retry can never double-count. New hypotheses are checked against the session's vectors with Atlas Vector Search: a paraphrase scored 0.989 and was dropped, an unrelated idea scored 0.68." |
| 2:45-3:00 | Slide or README table: Atlas Search, Vector Search, Hybrid Search ($rankFusion), Automated Embedding, transactions, Voyage embeddings and rerank. | "Atlas as the core store, Atlas Search, Vector Search, hybrid search, Automated Embedding, transactions, and Voyage for embeddings and reranking. An AI co-scientist whose evidence you can trace. Thank you." |

## Pre-flight checklist

- [ ] `co-scientist library stats` shows passages > 0 and both indexes `queryable=True`.
- [ ] A finished session exists on the Atlas backend; note its id for `co-scientist report <id>`.
- [ ] The top hypothesis cites at least one `#F…` or `#s….p…` URL (check `data/artifacts/<session_id>/` or the hypothesis page).
- [ ] `elo_journal` has one document per valid match.
- [ ] No connection string or API key visible in any shot.
