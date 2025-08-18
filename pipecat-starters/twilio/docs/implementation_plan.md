## Implementatieplan — Pipecat integratie met OpenAI, Twilio en tools (N8N)

Dit plan beschrijft hoe we de geoptimaliseerde system prompt en tools uit `docs/system_prompt.md` en `docs/tools.md` integreren in de bestaande Pipecat‑pipeline in `bot.py`, en hoe we dit testen en uitrollen.

### 1) Voorwaarden en versies
- Python 3.10+
- API keys: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`)
- Pipecat pipeline (telephony via Twilio WebSocket) met VAD en DTMF is al aanwezig in `bot.py`.

Referenties:
- DTMF Aggregator en Twilio serializer: `docs.pipecat.ai/server/utilities/dtmf-aggregator`
- Twilio WebSockets integratie: `docs.pipecat.ai/guides/telephony/twilio-websockets`
- OpenAI LLM service en tools: `docs.pipecat.ai/server/services/llm/openai`
- Voorbeelden (Twilio, telephony, function calling): `https://github.com/pipecat-ai/pipecat-examples`

### 2) System prompt laden
Doel: vervang de hard‑gecodeerde system prompt in `bot.py` door de inhoud van `docs/system_prompt.md`.

Stappen:
1. Lees de Markdown in en gebruik alleen de tekstinhoud voor het system‑bericht.
2. Stel de `messages` variabele gelijk aan één `{"role":"system","content": <geladen tekst>}`.
3. Laat de assistant de conversatie openen door het system‑kader te pushen bij connect (is al aanwezig via `context_aggregator.user().get_context_frame()`).

Tip: Gebruik `LLMMessagesUpdateFrame`/`LLMMessagesAppendFrame` wanneer je runtime updates wilt doen aan de context. Zie `docs.pipecat.ai/server/services/llm/openai` en `docs.pipecat.ai/server/docs/frame.md`.

### 3) Tools registreren (function calling)
Doel: exposeer de N8N‑webhooks als tools voor het LLM volgens de specificaties in `docs/tools.md`.

Stappen:
1. Definieer schemas voor tools met `FunctionSchema` en groepeer ze in `ToolsSchema`.
2. Geef de `tools` door aan `OpenAILLMContext`.
3. Registreer per tool een async handler die de webhook aanroept en het resultaat via `params.result_callback({...})` teruggeeft.

Voorbeeld (vereenvoudigd) voor `get_instructions` en `pd_nr_check`:
```python
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams
import aiohttp

get_instructions_fn = FunctionSchema(
    name="get_instructions",
    description=(
        "Haal instructies op voor het bieden van een oplossing op basis van de probleemomschrijving."
    ),
    properties={
        "probleemomschrijving": {"type": "string", "description": "Probleembeschrijving"}
    },
    required=["probleemomschrijving"],
)

pd_nr_check_fn = FunctionSchema(
    name="pd_nr_check",
    description="Controleer of het nummer van de parkeerautomaat correct is.",
    properties={"pd_nr": {"type": "string", "description": "Automaatnummer (4 cijfers)"}},
    required=["pd_nr"],
)

tools_schema = ToolsSchema(standard_tools=[get_instructions_fn, pd_nr_check_fn])

# In OpenAILLMContext(..., tools=tools_schema)

async def call_get_instructions(params: FunctionCallParams):
    async with aiohttp.ClientSession() as s:
        body = {"probleemomschrijving": params.arguments.get("probleemomschrijving", "")}
        async with s.post("https://henk.taxameter.nl/webhook/get_instructions", json=body, timeout=8) as r:
            data = await r.json(content_type=None)
    await params.result_callback(data)

async def call_pd_nr_check(params: FunctionCallParams):
    async with aiohttp.ClientSession() as s:
        body = {"pd_nr": params.arguments.get("pd_nr", "")}
        async with s.post("https://henk.taxameter.nl/webhook/pd_nr_check", json=body, timeout=6) as r:
            data = await r.json(content_type=None)
    await params.result_callback(data)

llm.register_function("get_instructions", call_get_instructions)
llm.register_function("pd_nr_check", call_pd_nr_check)
```

Belangrijk:
- Houd timeouts kort (6–10s) en geef duidelijke foutberichten terug bij netwerkfouten.
- Spreek tijdens uitvoering: laat het LLM dit zelf doen volgens de prompt (“Even kijken…”), of push optioneel een korte `TextFrame` vóór de call om stilte te voorkomen.
- Gebruik dezelfde aanpak voor de overige tools (`solution_path_flow`, `transactie_controle_snel`, `status_checker`, `automaat_in_de_buurt`, `parkeerhulp`, `stuur_lokatie_sms`, `gemeente_bezwaar`, `transfer_call`, `end_call`).

Referenties:
- Function calling met OpenAI‑context: `docs.pipecat.ai/guides/fundamentals/function-calling`
- OpenAI LLM + context + tools: `docs.pipecat.ai/server/services/llm/openai`

### 4) DTMF en turn‑taking
Doel: robuuste verwerking van DTMF vóór STT en korte TTS‑zinnen voor barge‑in.

Stappen:
1. Zorg dat `DTMFAggregator` vóór STT staat (is zo in `bot.py`).
2. Blijf sample rate 8kHz voor Twilio (reeds ingesteld in `PipelineParams`).
3. VAD: `SileroVADAnalyzer()` actief laten om segmentatie/interruptions te sturen.

Referenties:
- DTMF Aggregator: `https://docs.pipecat.ai/server/utilities/dtmf-aggregator`

### 5) Observability en betrouwbaarheid
Doel: inzicht in latency en tool‑succesratio’s.

Stappen:
1. `enable_metrics=True` en `enable_usage_metrics=True` (reeds in `bot.py`).
2. Optioneel: voeg `DebugLogObserver` toe voor frame‑logging in ontwikkelomgeving.
3. Log per tool: duur, statuscode, responsvorm; corrigeer ongeldige JSON en timeouts.

### 6) Testplan (end‑to‑end)
Testset (minimaal):
- Introductie + algemene kennis (tarieven/boetes/vooraf betalen) zonder tools.
- `get_instructions` gevolgd door `pd_nr_check` (succes en foutpad).
- DTMF: 4 cijfers + ‘#’; 2× mis → dicteren en herhalen.
- `solution_path_flow` met respons tot “INSTRUCTIES”.
- `parkeerhulp` stap‑voor‑stap (pauzeren tussen stappen).
- Alternatieve automaat + `stuur_lokatie_sms` na toestemming.
- Handover: bevestigingsvraag → `transfer_call`; afsluiten met `end_call`.
- Foutpaden: timeouts/malformed JSON → korte technische storingsboodschap.

Praktisch:
- Gebruik ngrok voor lokale WebSocket/Twilio tests.
- Mock N8N‑webhooks voor deterministische scenario’s.

Referenties:
- Twilio WebSockets guide: `https://docs.pipecat.ai/guides/telephony/twilio-websockets`
- Pipecat telephony examples: `https://github.com/pipecat-ai/pipecat-examples`

### 7) Deploy (Pipecat Cloud/Twilio)
Stappen (indicatief):
1. Zet secrets in `.env`/deploy‑vars (OpenAI/Deepgram/ElevenLabs/Twilio).
2. Controleer Telephony webhook configuratie (Twilio → Pipecat server/Cloud).
3. Smoke test: inkomende call, korte dialoog, DTMF, één toolcall.
4. Activeer tracing/metrics in productie, monitor TTFB en tool‑timeouts.

### 8) Acceptatiecriteria
- Instructievolging: 100% volgens `docs/system_prompt.md` in testscenario’s.
- Geen hallucinatierisico: tools/algemene kennis only; geen verzinsels.
- DTMF herkent 4 cijfers + ‘#’, foutafhandeling werkt.
- Toolketen (get_instructions → pd_nr_check → solution_path_flow) werkt met fallsbacks.
- TTS‑uitspraakregels (cijfers, geld, tijden) consistent.

### 9) Eventuele code‑aanpassingen in `bot.py` (overzicht)
- System prompt laden uit bestand i.p.v. hard‑gecodeerd.
- Schema’s voor tools definiëren en registreren bij `OpenAILLMContext`.
- Async handlers implementeren voor N8N‑webhooks (aiohttp/httpx), met timeouts.
- Optioneel: pre‑exec korte `TextFrame` om stilte te vermijden bij lange toolcalls.

Nuttige verwijzingen
- DTMF Aggregator: `https://docs.pipecat.ai/server/utilities/dtmf-aggregator`
- OpenAI LLM service + context/tools: `https://docs.pipecat.ai/server/services/llm/openai`
- Twilio WebSockets guide: `https://docs.pipecat.ai/guides/telephony/twilio-websockets`
- OpenAI audio modellen & API’s: `https://docs.pipecat.ai/guides/features/openai-audio-models-and-apis`
- Pipecat examples (telephony, Twilio): `https://github.com/pipecat-ai/pipecat-examples`


