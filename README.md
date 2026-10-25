
# BioCurate: the Co-Co-Scientist built on Gemini-4-Argon and MongoDB

**Give it a research goal. Get back a transparent view of how agents generated and ranked a set of novel, reviewed, testable hypotheses.**

> ### 🚀 Explore BioCurate live
>
> **[🧬 OPEN THE LIVE APP →](https://e218-193-221-143-82.ngrok-free.app)**
>
> *Try a research prompt and follow the agents as they analyze, review, and rank hypotheses.*

## What we built
Introducing BioCurate, a multi-agent auditor to the agentic scientist, instilling transparent research provenance into Google Deepmind’s Co-Scientist. This empowers scientists to critically evaluate how AI-generated hypotheses are proposed, supported, and ranked.

We are extending Co-Scientist with two critical, specialised agents:

**Data Analysis Agent**: Performs reproducible, clinically-relevant statistical analyses on scientist-uploaded datasets, independently evaluating proposed hypotheses against empirical evidence.

**LitTrace Agent**: Traces the literature and experimental evidence underlying Co-Scientist's generated hypotheses, identifying the specific findings, data, and levels of evidence from sourced studies that shape literature interpretations and inform hypothesis generation and ranking.

Through an interactive interface, scientists can inspect the evidence behind each hypothesis, explore supporting and contradictory findings, examine statistical analyses, and understand how hypotheses evolve through BioCurate's review and ranking process. 

Our goal is to make AI-driven scientific discovery transparent, auditable, and scientist-directed, restoring human agency over the agent-driven research processes.
The problem it solves
Agentic scientists like Google's Co-Scientist are accelerating scientific discovery by autonomously generating, reviewing, and ranking research hypotheses. However, the quality of these hypotheses is fundamentally dependent on the quality, accuracy, and precision of the scientific literature and data they draw upon.

Published research contains conflicting findings, methodological limitations, and occasionally erroneous or irreproducible results, and tends to be systemically biased against negative results. Without robust verification, AI scientists risk propagating these weaknesses and  into seemingly convincing hypotheses.

Furthermore, the process by which AI agents select evidence, evaluate hypotheses, and determine rankings is often difficult for researchers to audit. Scientists may receive promising research recommendations without a clear, inspectable account of which experimental findings influenced those recommendations or why particular hypotheses were prioritised.

We are addressing this evidence-quality and transparency gap for biomedical researchers, scientific research teams, and developers of autonomous AI scientists.

By integrating reproducible statistical analysis with evidence-level provenance and meta-review, our system enables scientists to independently validate AI-generated hypotheses, interrogate the evidence informing their rankings, and identify unsupported or contradictory findings.

Rather than replacing scientific judgement, we aim to return control to researchers—transforming AI Co-Scientist from a system that generates recommendations into one whose recommendations scientists can meaningfully inspect, challenge, and verify.

## How it works
The agent roster and control flow follow the original Google Co-Scientist paper (Gottweis et al. Nature, 2026), with the addition of a Data Analysis agent (for ingestion and statistical analysis of user-provided data) and a LitTrace agent (for pinpointing the exact data and evidence in literature sourced in literature review).

| Agent | What it does |
|---|---|
| **Supervisor** | Parses the goal into a research plan and schedules agent tasks through a durable SQLite-backed queue with bounded concurrency. It stops on whichever comes first: budget, wall clock, Elo stability, or an idle queue. |
| **Data Analysis** | Runs statistical screening and analyses on input data, emitting results that feed into hypothesis generation and ranking. |
| **Generation** | Proposes hypotheses through literature review and simulated scientific debate. |
| **Reflection** | Reviews for novelty, correctness and testability, and deep-verifies the assumptions underneath. |
| **Ranking** | Runs an Elo tournament of simulated debates between hypotheses. |
| **Evolution** | Combines, simplifies, makes feasible, or reimagines top-ranked hypotheses out of the box. |
| **Proximity** | Embeds and clusters hypotheses to drive de-duplication and informative tournament pairings. |
| **LitTrace** | Extracts the specific lines/findings in sourced literature, synthesizes system-wide feedback and writes the final research overview with clear provenance of literature evidence. |


## What’s next
With the provenance made transparent by BioCurate, this hypothesis-augmentation workflow can be embedded into a larger agentic framework. For instance, hypotheses generated from BioCurate, complete with the evidence audit trail, can be used to inform selection of appropriate and relevant datasets for further analyses, prioritization and design of bioinformatics approaches for analyses, and proposal of follow-up wet-lab experiments.

