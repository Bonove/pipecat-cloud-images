# Twilio Voice Bot Starter

A telephone-based conversational agent built with Pipecat that connects to Twilio for voice calls.

## Features

- Telephone voice conversations powered by:
  - Deepgram (STT)
  - OpenAI (LLM)
  - ElevenLabs (TTS)
- Voice activity detection with Silero
- FastAPI WebSocket connection with Twilio
- 8kHz audio sampling optimized for telephone calls

## Required API Keys

- `OPENAI_API_KEY`
- `DEEPGRAM_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- Twilio account with Media Streams configured

## Quick Customization

### Change Bot Personality

Modify the system prompt in `bot.py`:

```python
messages = [
    {
        "role": "system",
        "content": "You are Chatbot, a friendly, helpful robot..."
    },
]
```

### Text-to-Speech provider

De TTS-service gebruikt ElevenLabs. De API-sleutels moeten als environment variables beschikbaar zijn (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`).

### Adjust Audio Parameters

The pipeline is configured for telephone-quality audio (8kHz). If your Twilio configuration uses different parameters, adjust these values:

```python
task = PipelineTask(
    pipeline,
    params=PipelineParams(
        audio_in_sample_rate=8000,  # Input sample rate
        audio_out_sample_rate=8000, # Output sample rate
        # Other parameters...
    ),
)
```

## Twilio Setup

To connect this agent to Twilio:

1. [Purchase a number from Twilio](https://help.twilio.com/articles/223135247-How-to-Search-for-and-Buy-a-Twilio-Phone-Number-from-Console), if you haven't already

2. Collect your Pipecat Cloud organization name:

```bash
pcc organizations list
```

You'll use this information in the next step.

3. Create a [TwiML Bin](https://help.twilio.com/articles/360043489573-Getting-started-with-TwiML-Bins):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://api.pipecat.daily.co/ws/twilio">
      <Parameter name="_pipecatCloudServiceHost" value="AGENT_NAME.ORGANIZATION_NAME"/>
    </Stream>
  </Connect>
</Response>
```

where:

- AGENT_NAME is your agent's name (the name you used when deploying)
- ORGANIZATION_NAME is the value returned in the previous step

4. Assign the TwiML Bin to your phone number:

- Select your number from the Twilio dashboard
- In the `Configure` tab, set `A call comes in` to `TwiML Bin`
- Set `TwiML Bin` to the Bin you created in the previous step
- Save your configuration

## Deployment

See the [top-level README](../README.md) for deployment instructions.

## Pipecat Flows: Visual Editor en JSON-export

Deze starter ondersteunt Pipecat Flows (Dynamic en Static Flows).

- Loader: bij start probeert de bot automatisch `flows/export.json` te laden en te initialiseren via `FlowManager`.
- Fallback: als er geen export is, worden Python-nodefabrieken gebruikt; als dat faalt, start de legacy kickoff.

### Visual Editor lokaal draaien

1. Clone de editor-repo (aparte map, buiten dit project is prima):

```bash
git clone https://github.com/pipecat-ai/pipecat-flows.git
cd pipecat-flows/editor
npm install
npm run dev
# Open http://localhost:5173
```

2. Ontwerp/aanpas je flow visueel en exporteer naar JSON.

3. Plaats de export als `flows/export.json` in dit project:

```bash
cp /pad/naar/export.json /Users/tristanvandoorn@makerlab.nl/Documents/pipecat-cloud-images/pipecat-starters/twilio/flows/export.json
```

Bij de volgende start gebruikt de bot automatisch deze flow.

Referenties:
- Docs: Pipecat Flows [server docs](https://docs.pipecat.ai/server/frameworks/flows/pipecat-flows)
- API: Actions [API](https://reference-flows.pipecat.ai/en/latest/api/pipecat_flows.actions.html)
