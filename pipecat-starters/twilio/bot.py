#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os

from dotenv import load_dotenv
from loguru import logger
from openai._types import NotGiven
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.aggregators.dtmf_aggregator import DTMFAggregator
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
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
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
        model="eleven_flash_v2_5",
    )

    # Set up the initial context for the conversation
    # You can specified initial system and assistant messages here
    messages = [
        {
            "role": "system",
            "content": "You are Samantha, a friendly, helpful service assistant, providing every service the customer needs. Your goal is to demonstrate your capabilities in a succinct way. Your output will be converted to audio so don't include special characters in your answers. Respond to what the user said in a creative and helpful way, but keep your responses brief. Start by introducing yourself. If you receive a transcription that starts with 'DTMF: ', treat it as keypad input that can appear mid-conversation. Expect a 4-digit code followed by '#', e.g., 'DTMF: 1234#'. When such input is received, extract the 4 digits and acknowledge them succinctly, then continue the conversation.",
            
        }cd "/Users/tristanvandoorn@makerlab.nl/Documents/pipecat-cloud-images/pipecat-starters/twilio"

git checkout feat/bot-iteraties,
    ]

    # Define and register tools as required
    tools = NotGiven()

    # This sets up the LLM context by providing messages and tools
    context = OpenAILLMContext(messages, tools)
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
