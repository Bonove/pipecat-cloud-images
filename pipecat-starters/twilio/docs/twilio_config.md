## Twilio configuratie (huidig)

### Actieve setup
- **Routing**: Inkomende calls → TwiML Bin (Stream)
- **Doel**: Pipecat Cloud WS endpoint
- **Parameters**:
  - `_pipecatCloudServiceHost`: `twilio-agent-henk1.makerstreet`
  - `track`: niet gezet (default inbound)

### TwiML Bin (Stream)
Gebruik onderstaande inhoud in je TwiML Bin. Deze wordt gekoppeld aan je telefoonnummer bij “A call comes in”.

```xml
<Response>
  <Connect>
    <Stream url="wss://api.pipecat.daily.co/ws/twilio">
      <Parameter name="_pipecatCloudServiceHost" value="twilio-agent-henk1.makerstreet"/>
    </Stream>
  </Connect>
  
</Response>
```

Opmerkingen:
- Laat `track` weg of gebruik `track="inbound_track"` als je het expliciet wil zetten. Vermijd ongeldige waarden zoals `both` (Twilio error 31941: Invalid Track configuration).
- deze stream‑bin stuurt géén dtmf‑events door. dtmf wordt niet als event zichtbaar in de media stream.

### nummer koppelen
1. twilio console → phone numbers → manage → active numbers → selecteer je nummer
2. “a call comes in” → twiml bin → kies de bovenstaande bin → save

### dtmf
- in de huidige setup lijkt DTMF te werken.

### Referenties
- Twilio DTMF: `https://www.twilio.com/docs/glossary/what-is-dtmf`
- Twilio Gather (voorbeeld): `https://www.twilio.com/docs/voice/tutorials/how-to-gather-user-input-via-keypad/python`
- Pipecat DTMF Aggregator: `https://docs.pipecat.ai/server/utilities/dtmf-aggregator#dtmfaggregator`


