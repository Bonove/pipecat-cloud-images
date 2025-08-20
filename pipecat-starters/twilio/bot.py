#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os

from dotenv import load_dotenv
import aiohttp
from loguru import logger
from openai._types import NotGiven
from langdetect import detect as detect_lang
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.aggregators.dtmf_aggregator import DTMFAggregator
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from deepgram import LiveOptions
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

try:  # Pipecat Flows is optioneel; als niet aanwezig, blijft oude startlogica actief
    from pipecat_flows import FlowManager  # type: ignore
    _flows_available = True
except Exception:
    FlowManager = None  # type: ignore
    _flows_available = False

try:
    from agents.flows import create_initial_node  # type: ignore
except Exception:
    create_initial_node = None  # type: ignore

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, call_id: str | None = None, initial_dtmf_code: str | None = None):
    """Run your bot with the provided transport.

    Args:
        transport (BaseTransport): The transport to use for communication.
    """
    # Configure your STT, LLM, and TTS services here
    # Swap out different processors or properties to customize your bot
    # Multi-language taaldetectie: probeer Deepgram met detectie (NL/EN). Val terug op NL-only indien nodig.
    try:
        if os.getenv("DEEPGRAM_DETECT_LANGUAGE", "1") == "1":
            stt = DeepgramSTTService(
                api_key=os.getenv("DEEPGRAM_API_KEY"),
                live_options=LiveOptions(
                    model="nova-3-general",
                    smart_format=True,
                    vad_events=True,
                    detect_language=True,  # Deepgram detecteert taal uit lijst
                    languages=["nl", "en"],
                ),
            )
        else:
            raise ValueError("language-detect disabled")
    except Exception:
        stt = DeepgramSTTService(
            api_key=os.getenv("DEEPGRAM_API_KEY"),
            live_options=LiveOptions(
                model="nova-3-general",
                language="nl",
                smart_format=True,
                vad_events=True,
            ),
        )
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
        model="eleven_flash_v2_5",
        params=ElevenLabsTTSService.InputParams(
            language=Language.NL,
            stability=0.7,
            similarity_boost=0.8,
            style=0.5,
            use_speaker_boost=True,
            speed=1.0,
        ),
    )

    # Set up the initial context for the conversation
    # Load system prompt from docs/system_prompt.md
    base_dir = os.path.dirname(os.path.abspath(__file__))
    system_prompt_path = os.path.join(base_dir, "docs", "system_prompt.md")
    try:
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            system_prompt_text = f.read()
    except Exception as e:
        logger.warning(f"Kon system prompt niet laden ({e}); val terug op standaard prompt")
        system_prompt_text = (
            "Je bent een Nederlandstalige telefonische assistent. Gebruik korte zinnen,"
            " volg strikt de opgegeven taken en spreek cijfers los uit."
        )

    messages = [
        {
            "role": "system",
            "content": system_prompt_text,
        }
    ]

    # Als via Twilio Gather een 4-cijferige code is meegegeven als stream-parameter,
    # voeg deze meteen toe als user-transcript zodat de LLM dit direct verwerkt.
    if initial_dtmf_code:
        cleaned = "".join(ch for ch in str(initial_dtmf_code) if ch.isdigit())[:4]
        if cleaned:
            messages.append({"role": "user", "content": f"DTMF: {cleaned}#"})

    # Define tools (function calling) and register handlers
    # Schemas zijn vereenvoudigd voor betere LLM-invulling; handlers mappen naar API-payloads
    get_instructions_fn = FunctionSchema(
        name="get_instructions",
        description=(
            "Gebruik deze tool om de instructies op te halen voor het bieden van een oplossing op basis van de probleemomschrijving."
        ),
        properties={
            "Probleemomschrijving": {
                "type": "string",
                "description": "De omschrijving van het probleem van de parkeerder",
            }
        },
        required=["Probleemomschrijving"],
    )

    pd_nr_check_fn = FunctionSchema(
        name="pd_nr_check",
        description="Controleer het automaatnummer en verifieer de locatie.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    parkeerhulp_fn = FunctionSchema(
        name="parkeerhulp",
        description="Haal instructies op om een kaartje te kopen bij de opgegeven automaat.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    stuur_lokatie_sms_fn = FunctionSchema(
        name="stuur_lokatie_sms",
        description="Verstuur een sms met de locatie van de werkende automaat.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    solution_path_flow_fn = FunctionSchema(
        name="solution_path_flow",
        description="Haal oplossingen op voor problemen, gegeven automaat en probleemomschrijving.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"},
            "Probleemomschrijving": {
                "type": "string",
                "description": "Probleemomschrijving van de beller",
            },
        },
        required=["pd_nr", "Probleemomschrijving"],
    )

    transactie_controle_snel_fn = FunctionSchema(
        name="transactie_controle_snel",
        description="Controleer of een tijdens het gesprek uitgevoerde betaling is gelukt.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    automaat_in_de_buurt_fn = FunctionSchema(
        name="automaat_in_de_buurt",
        description="Zoek een alternatieve, werkende automaat in de buurt.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    transactie_checker_fn = FunctionSchema(
        name="transactie_checker",
        description="Controleer recente transacties op een automaat.",
        properties={
            "pd_nr": {"type": "integer", "description": "Automaatnummer (1000-2029)"}
        },
        required=["pd_nr"],
    )

    gemeente_bezwaar_fn = FunctionSchema(
        name="gemeente_bezwaar",
        description=(
            "Stuur een SMS met informatie over bezwaar tegen een gemeentelijke boete."
        ),
        properties={
            "klant_id": {
                "type": "integer",
                "description": "Standaard 1000435",
            }
        },
        required=[],
    )

    rapportage_tool_fn = FunctionSchema(
        name="rapportage_tool",
        description="Verzend transcript en call_id naar rapportage endpoint (fire-and-forget).",
        properties={},
        required=[],
    )

    tools_schema = ToolsSchema(
        standard_tools=[
            get_instructions_fn,
            pd_nr_check_fn,
            parkeerhulp_fn,
            stuur_lokatie_sms_fn,
            solution_path_flow_fn,
            transactie_controle_snel_fn,
            automaat_in_de_buurt_fn,
            transactie_checker_fn,
            gemeente_bezwaar_fn,
            rapportage_tool_fn,
        ]
    )

    # Handlers
    async def _post_json(url: str, body: dict, timeout: float = 8.0):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=body, timeout=timeout) as r:
                    return await r.json(content_type=None)
        except Exception as e:
            return {"error": f"request_failed: {str(e)}"}

    async def _wrap_pd_nr(pd_nr: int) -> dict:
        return {
            "maximum": 2029,
            "type": "integer",
            "value": int(pd_nr),
            "minimum": 1000,
        }

    async def h_get_instructions(params: FunctionCallParams):
        body = {
            "Probleemomschrijving": params.arguments.get("Probleemomschrijving", ""),
            "call_id": call_id,
        }
        data = await _post_json("https://henk.taxameter.nl/webhook/get_instructions", body)
        await params.result_callback(data)

    async def h_pd_nr_check(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr), "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/locatie_informatie", body)
        await params.result_callback(data)

    async def h_parkeerhulp(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr), "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/parkeer_hulp", body)
        await params.result_callback(data)

    async def h_stuur_lokatie_sms(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr), "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/sms_lokatie_informatie", body)
        await params.result_callback(data)

    async def h_solution_path_flow(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        probleem = params.arguments.get("Probleemomschrijving", "")
        body = {"pd_nr": pd_nr, "Probleemomschrijving": probleem, "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/solution_path_flow", body)
        await params.result_callback(data)

    async def h_transactie_controle_snel(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr), "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/transactie_controle_snel", body)
        await params.result_callback(data)

    async def h_automaat_in_de_buurt(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": pd_nr, "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/automaat-in-de-buurt", body)
        await params.result_callback(data)

    async def h_transactie_checker(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": pd_nr, "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/laatste_transacties", body)
        await params.result_callback(data)

    async def h_gemeente_bezwaar(params: FunctionCallParams):
        klant_id = int(params.arguments.get("klant_id", 1000435))
        body = {"klant_id": klant_id, "call_id": call_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/bezwaar-gemeente", body)
        await params.result_callback(data)

    async def h_rapportage_tool(params: FunctionCallParams):
        # Bouw transcript uit contextmessages; stuur asynchroon naar rapportage endpoint
        try:
            msgs = context.get_messages_json() if hasattr(context, "get_messages_json") else []
            text_parts = []
            for m in msgs:
                role = m.get("role")
                content = m.get("content")
                if isinstance(content, str):
                    text_parts.append(f"{role}: {content}")
            transcript = "\n".join(text_parts)
        except Exception:
            transcript = ""

        payload = {"call_id": call_id, "transcript": transcript}

        async def _send():
            await _post_json("https://henk.taxameter.nl/webhook/pipecat-rapportage", payload, timeout=5.0)

        import asyncio
        asyncio.create_task(_send())
        await params.result_callback({"ok": True})

    # Register functions
    llm.register_function("get_instructions", h_get_instructions)
    llm.register_function("pd_nr_check", h_pd_nr_check)
    llm.register_function("parkeerhulp", h_parkeerhulp)
    llm.register_function("stuur_lokatie_sms", h_stuur_lokatie_sms)
    llm.register_function("solution_path_flow", h_solution_path_flow)
    llm.register_function("transactie_controle_snel", h_transactie_controle_snel)
    llm.register_function("automaat_in_de_buurt", h_automaat_in_de_buurt)
    llm.register_function("transactie_checker", h_transactie_checker)
    llm.register_function("gemeente_bezwaar", h_gemeente_bezwaar)
    llm.register_function("rapportage_tool", h_rapportage_tool)

    # This sets up the LLM context by providing messages and tools
    context = OpenAILLMContext(messages, tools_schema)
    context_aggregator = llm.create_context_aggregator(context)

    # A core voice AI pipeline
    # Add additional processors to customize the bot's behavior
    dtmf = DTMFAggregator(timeout=5.0)
    pipeline = Pipeline(
        [
            transport.input(),
            dtmf,
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected: {client}")
        if _flows_available:
            try:
                # Probeer eerst een statische flow-config te laden vanuit flows/export.json
                flow_config = None
                export_path = os.path.join(base_dir, "flows", "export.json")
                if os.path.exists(export_path):
                    import json
                    with open(export_path, "r", encoding="utf-8") as f:
                        flow_config = json.load(f)

                fm_kwargs = {
                    "task": task,
                    "llm": llm,
                    "context_aggregator": context_aggregator,
                    "transport": transport,
                }
                if flow_config:
                    fm_kwargs["flow_config"] = flow_config

                flow_manager = FlowManager(**fm_kwargs)  # type: ignore

                if flow_config:
                    # Statische flow start via initial_node in config
                    await flow_manager.initialize(flow_config["nodes"][flow_config["initial_node"]])
                elif create_initial_node is not None:
                    # Dynamische fallback met Python node-fabriek
                    await flow_manager.initialize(create_initial_node(system_prompt_text))
                else:
                    # Laatste fallback: legacy kickoff
                    await task.queue_frames([context_aggregator.user().get_context_frame()])
                return
            except Exception as e:
                logger.warning(f"Flows initialize mislukt, val terug op legacy start ({e})")
        # Legacy kickoff
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    # Dynamische TTS-taalswitch op basis van eerste user-utterance
    @transport.event_handler("on_user_transcript")
    async def on_user_transcript(transport, transcript: str):
        # Basic guardrails
        if not transcript or len(transcript) < 2:
            return
        try:
            code = detect_lang(transcript)  # bv. 'en', 'nl', 'de', 'fr'
        except Exception:
            return

        # Map naar Pipecat Language
        lang_map = {
            "en": Language.EN,
            "nl": Language.NL,
            "de": Language.DE,
            "fr": Language.FR,
        }
        new_lang = lang_map.get(code)
        if not new_lang:
            return

        # Alleen wijzigen indien anders dan huidige setting
        try:
            current = tts.params.language if hasattr(tts, "params") else None
        except Exception:
            current = None

        if current == new_lang:
            return

        try:
            # Geen voice_id wissel; enkel taal updaten
            tts.update_setting("params.language", new_lang)
            logger.info(f"TTS language switched to {new_lang}")
        except Exception as e:
            logger.warning(f"Kon TTS-taal niet wisselen: {e}")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected: {client}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False, force_gc=True)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""

    transport = None

    krisp_filter = None
    if os.environ.get("ENV") != "local":
        try:
            from pipecat.audio.filters.krisp_filter import KrispFilter
            krisp_filter = KrispFilter()
        except Exception as e:
            logger.warning(f"Krisp filter niet beschikbaar ({e}); ga door zonder noise suppression")

    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    logger.info(f"Auto-detected transport: {transport_type}")

    # Create transport based on detected type
    if transport_type == "twilio":
        from pipecat.serializers.twilio import TwilioFrameSerializer

        serializer = TwilioFrameSerializer(
            stream_sid=call_data["stream_id"],
            call_sid=call_data["call_id"],
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        )

    else:
        logger.error(f"Unsupported telephony provider: {transport_type}")
        return

    # Create the transport
    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
        ),
    )

    if transport is None:
        logger.error("Failed to create transport")
        return

    try:
        await run_bot(
            transport,
            call_id=call_data.get("call_id"),
            initial_dtmf_code=call_data.get("initial_dtmf_code"),
        )
        logger.info("Bot process completed")
    except Exception as e:
        logger.exception(f"Error in bot process: {str(e)}")
        raise


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
