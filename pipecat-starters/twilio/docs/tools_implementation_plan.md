## Tools Implementatieplan — Pipecat + OpenAI + N8N

Doel: alle tools uit `docs/tools.md` beschikbaar maken via OpenAI function calling in Pipecat, inclusief webhook‑handlers (N8N), foutafhandeling, logging en tests.

### 0) Scope en uitgangspunten
- Platform: Pipecat server, telephony via Twilio WebSocket, STT Deepgram, TTS ElevenLabs, LLM OpenAI (cascaded pipeline in `bot.py`).
- System prompt komt uit `docs/system_prompt.md` en dicteert toolvolgorde en spreekregels.
- DTMF wordt al geaggregeerd vóór STT (zie `DTMFAggregator`).

Referenties:
- DTMFAggregator en Twilio serializer: https://docs.pipecat.ai/server/utilities/dtmf-aggregator
- OpenAI LLM + context/tools: https://docs.pipecat.ai/server/services/llm/openai
- Function calling in pipeline: https://docs.pipecat.ai/guides/fundamentals/function-calling
- Pipecat examples (telephony, Twilio): https://github.com/pipecat-ai/pipecat-examples

### 1) Dependencies en configuratie
- Voeg HTTP‑client toe voor webhook‑calls: `aiohttp` of `httpx` (async). Aanbevolen: `aiohttp`.
- Zet per tool timeout (6–10s) en herbruik één `ClientSession` (lifecycle = app).
- Bewaar base‑URL’s in env als je varianten wilt kunnen wisselen (desnoods nu hard‑coded uit `docs/tools.md`).

### 2) Tool schema’s definiëren
- Voor elke tool in `docs/tools.md`: maak een `FunctionSchema` met exacte `name`, `description`, `properties`, `required`.
- Groepeer in één `ToolsSchema` en geef dit door aan `OpenAILLMContext(..., tools=tools_schema)` vóór het bouwen van de pipeline.

Aanwijzingen (Pipecat):
- Gebruik `OpenAILLMContext(messages=[{"role":"system",...}], tools=tools_schema)`
- Maak een `context_aggregator = llm.create_context_aggregator(context)` en gebruik die in de pipeline vóór/na `llm`.

### 3) Handlers registreren (webhooks N8N)
- Registreer per tool een async handler met `llm.register_function(<name>, <callable>)`.
- Handlerpatroon:
  1) Valideer/normaliseer arguments (`params.arguments`).
  2) `POST` naar de webhook met `json` body.
  3) Parse JSON veilig (`await r.json(content_type=None)`), map naar verwacht formaat (bijv. `{ "output": ... }`).
  4) `await params.result_callback(<json>)` teruggeven aan LLM.
  5) Exceptions → gestandaardiseerde fout (`{"error": "<kort bericht>"}`) teruggeven zodat de prompt de fallback‑zin kan spreken.

Best practices:
- Timeouts strikt; geen retries in handler (LLM kan opnieuw proberen).
- Logging: endpoint, duur, status (200/4xx/5xx), payload‑grootte.
- Minimale afhankelijkheden; hergebruik 1 `aiohttp.ClientSession`.

### 4) Toolkeuzes en LLM‑instellingen
- `tool_choice="auto"` zodat het LLM tools mag aanroepen, tenzij je in specifieke flows `required` wilt forceren.
- Prompt dicteert: eerst `get_instructions` als algemene kennis niet volstaat; daarna pas vervolgtools.
- Spreekfeedback tijdens call (“Even kijken…”) komt uit prompt; geen aparte TTS‑injecties nodig.

### 5) Mapping per tool (payload/succes/fout)
- `get_instructions`: body `{ probleemomschrijving }` → verwacht `{ output, INSTRUCTIES? }` (spreek tot "INSTRUCTIES").
- `pd_nr_check`: body `{ pd_nr }` → verwacht `{ message }`; spreek bevestiging “Ik heb de parkeerautomaat gevonden. Even kijken.”
- `solution_path_flow`: body `{ pd_nr, probleemomschrijving }` → verwacht `{ output, ... }`; spreek tot "INSTRUCTIES".
- `transactie_controle_snel`: body `{ pd_nr }` → bevestig wel/niet gelukt.
- `transactie_checker`: body `{ pd_nr }` → vat kern samen.
- `status_checker`: body `{ pd_nr }` → vat status samen.
- `automaat_in_de_buurt`: body `{ pd_nr }` → bied sms aan; na akkoord: `stuur_lokatie_sms`.
- `parkeerhulp`: body `{ pd_nr }` → lees stap‑voor‑stap, wacht per stap op beller.
- `stuur_lokatie_sms`: body `{ telefoonnummer, locatie }` → bevestig verzending.
- `gemeente_bezwaar`: body `{ klant_id: "1000435" }` → bevestig verzending.
- `transfer_call`: body `{ reden? }` → bevestig overdracht.
- `end_call`: geen body → netjes afsluiten.
- `press_digit`: geen webhook; DTMF via `DTMFAggregator` (parse 4 cijfers + `#`).

Opmerking: houd je aan exacte velden en types zoals in `docs/tools.md`.

### 6) Foutafhandeling en robuustheid
- 4xx/5xx/timeout/malformed JSON → geef `{ "error": "<kort>" }` terug; de prompt laat de agent een korte storingsboodschap uitspreken.
- Null/lege `output` → behandel als onverwachte respons.
- DTMF: bij mis-parse → vraag opnieuw, spreek cijfers uit, bied dicteren als alternatief.

### 7) Observability
- Houd `enable_metrics` en `enable_usage_metrics` aan.
- Voeg eenvoudige logging toe rond elke handler (duur, status, toolnaam).
- Optioneel: `DebugLogObserver` in dev om frameflow te inspecteren.

### 8) Testplan (per tool en e2e)
Unit (mock N8N):
- Succes‑responsen met alle velden.
- Fouten: 400/500/timeout/lege body/malformed JSON.
Integratie (telephony):
- Scenario’s uit `docs/implementation_plan.md` (DTMF, get_instructions → pd_nr_check → solution_path_flow, parkeerhulp, sms, handover, end_call).
- Controleer uitspraakregels (cijfers/geld/tijden) en barge‑in.

Praktisch:
- Gebruik ngrok voor lokale Twilio tests.
- Log stub payloads en responses voor regressie.

### 9) Uitrol
1) Secrets en endpoints controleren.
2) Smoke test: één inkomend gesprek, één toolcall.
3) Monitoring: latencies, foutpercentages per tool.
4) Rollback: toggle tools (tool_choice="none") of revert naar vorige build.

### 10) Code‑ankers in `bot.py` (wijzigingen op hoog niveau)
- Vervang `tools = NotGiven()` door `tools=tools_schema` in `OpenAILLMContext`.
- Registreer alle `llm.register_function(...)` vóór het bouwen van de pipeline.
- Deel één `aiohttp.ClientSession` instance binnen de lifecycle (optioneel: lazy init bij eerste toolcall).

—
Bronnen:
- DTMFAggregator: https://docs.pipecat.ai/server/utilities/dtmf-aggregator
- OpenAI LLM + context/tools: https://docs.pipecat.ai/server/services/llm/openai
- Function calling: https://docs.pipecat.ai/guides/fundamentals/function-calling
- Pipecat examples (Twilio/telephony): https://github.com/pipecat-ai/pipecat-examples


