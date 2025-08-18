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

load_dotenv(override=True)


async def run_bot(transport: BaseTransport):
    """Run your bot with the provided transport.

    Args:
        transport (BaseTransport): The transport to use for communication.
    """
    # Configure your STT, LLM, and TTS services here
    # Swap out different processors or properties to customize your bot
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
        body = {"Probleemomschrijving": params.arguments.get("Probleemomschrijving", "")}
        data = await _post_json("https://henk.taxameter.nl/webhook/get_instructions", body)
        await params.result_callback(data)

    async def h_pd_nr_check(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr)}
        data = await _post_json("https://henk.taxameter.nl/webhook/locatie_informatie", body)
        await params.result_callback(data)

    async def h_parkeerhulp(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr)}
        data = await _post_json("https://henk.taxameter.nl/webhook/parkeer_hulp", body)
        await params.result_callback(data)

    async def h_stuur_lokatie_sms(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr)}
        data = await _post_json("https://henk.taxameter.nl/webhook/sms_lokatie_informatie", body)
        await params.result_callback(data)

    async def h_solution_path_flow(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        probleem = params.arguments.get("Probleemomschrijving", "")
        body = {"pd_nr": pd_nr, "Probleemomschrijving": probleem}
        data = await _post_json("https://henk.taxameter.nl/webhook/solution_path_flow", body)
        await params.result_callback(data)

    async def h_transactie_controle_snel(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": await _wrap_pd_nr(pd_nr)}
        data = await _post_json("https://henk.taxameter.nl/webhook/transactie_controle_snel", body)
        await params.result_callback(data)

    async def h_automaat_in_de_buurt(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": pd_nr}
        data = await _post_json("https://henk.taxameter.nl/webhook/automaat-in-de-buurt", body)
        await params.result_callback(data)

    async def h_transactie_checker(params: FunctionCallParams):
        pd_nr = int(params.arguments.get("pd_nr", 0))
        body = {"pd_nr": pd_nr}
        data = await _post_json("https://henk.taxameter.nl/webhook/laatste_transacties", body)
        await params.result_callback(data)

    async def h_gemeente_bezwaar(params: FunctionCallParams):
        klant_id = int(params.arguments.get("klant_id", 1000435))
        body = {"klant_id": klant_id}
        data = await _post_json("https://henk.taxameter.nl/webhook/bezwaar-gemeente", body)
        await params.result_callback(data)

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
        # Kick off the conversation
        await task.queue_frames([context_aggregator.user().get_context_frame()])

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
        await run_bot(transport)
        logger.info("Bot process completed")
    except Exception as e:
        logger.exception(f"Error in bot process: {str(e)}")
        raise


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
