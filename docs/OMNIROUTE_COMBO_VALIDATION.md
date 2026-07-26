# OmniRoute Combo Validation — 2026-07-26

Guardian audited and exercised the eight exact local OmniRoute combos requested
by the project owner. Membership was fetched from `http://localhost:3000/api/combos`
immediately before testing. Every successful completion was also re-audited by
Guardian immediately before the request.

All eight routes are recorded as `free-limited`: the user confirmed that they
consume finite daily/free quota rather than metered payment. Guardian still
tracks their token use, quota/rate-limit headers, latency, and failures.

| Combo | Audited pool | Result | Reported tokens |
| --- | --- | --- | ---: |
| `claude-opus-4.5` | KR Claude/DeepSeek/MiniMax/GLM pool | Exact `OK` | 6,146 |
| `claude-3.5-sonnet` | Antigravity Gemini/GPT-OSS pool | Exact `OK` | 2,242 |
| `claude-sonnet-4` | NVIDIA Nemotron/MiniMax/DeepSeek/GLM pool | Responded; did not finish exact response inside 8-token cap | 2,035 |
| `claude-3.7-sonnet` | Antigravity Gemini pool | Exact `OK` | 2,238 |
| `claude-opus-5` | `cgpt-web/gpt-5.5` | Exact `OK` | 2,007 |
| `claude-opus` | Qwen 3.7/3.6 web pool | Exact `OK` | 2,117 |
| `claude-sonnet` | DeepSeek web/reasoning pool | Exact `OK` | 2,000 |
| `claude-3-sonnet` | Bedrock GLM/GPT-OSS/Qwen Coder pool | Exact `OK` | 2,019 |

Successful smoke checks consumed 20,804 provider-reported tokens in total. A
single 32-token retry of `claude-sonnet-4` timed out and is not included in that
total. This validates connectivity, policy, and minimal instruction following;
it is not a broad quality benchmark.

## Routing policy

- Local Ollama remains first for ordinary work because the OmniRoute wrapper
  adds roughly 2,000 or more prompt tokens even to tiny requests.
- Free-limited combos form the bounded fallback pool.
- Failover tries one best local route, then independent OmniRoute combos, rather
  than exhausting the attempt budget on models behind one failed local backend.
- Qwen and other strong pools are marked `specialist`.
- `claude-opus-5` / GPT-5.5 is marked `final-review` and held later in the
  route order for high-value synthesis.
- `claude-sonnet-4.6` remains prohibited. Combo membership is re-audited before
  every completion, so a future unsafe membership change stops execution.
- Up to five routes may be attempted for one request. This bound prevents a
  quota outage from multiplying token use across every configured combo.

Provider-reported equivalent monetary value from prepaid/free-limited routes is
retained for analytics but is not counted as incremental billed cost. Metered
routes without verified pricing remain fail-closed unless the user explicitly
classifies an exact audited combo as free-limited.

## Redacted log health

Guardian also audits `http://localhost:3000/api/usage/logs` locally. Raw log
lines and connection identifiers are discarded; only model, provider, HTTP
status, and token counts are retained. The first 100-event audit found 38
failure events and produced these bounded routing penalties:

| Combo | Last status | Recent successes / failures | Penalty |
| --- | ---: | ---: | ---: |
| `claude-sonnet-4` | 499 | 2 / 3 | 30 |
| `claude-opus-4.5` | 499 | 13 / 6 | 15 |
| `claude-3.5-sonnet` | 499 | 14 / 6 | 15 |
| `claude-3.7-sonnet` | 200 | 11 / 0 | 0 |
| `claude-opus-5` | 200 | 4 / 0 | 0 |
| `claude-opus` | 200 | 4 / 0 | 0 |
| `claude-sonnet` | 200 | 1 / 0 | 0 |
| `claude-3-sonnet` | 200 | 6 / 1 | 0 |

This is operational evidence, not a permanent quality ranking. A zero-completion
maintenance job refreshes it every 15 minutes so recovered routes can move back
up and newly unstable pools can be demoted.
