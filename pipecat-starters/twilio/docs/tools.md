## Tools — Henk (Pipecat + OpenAI)

Algemeen: Tools worden via function calling aangeroepen. I/O gaat via N8N‑webhooks. Tijdens uitvoering spreek je de aangegeven begeleidende tekst uit. Na uitvoering spreek je de relevante boodschap voor de beller uit, maar nooit de sectie "INSTRUCTIES".

Belangrijke volgorde: gebruik altijd eerst `get_instructions` wanneer algemene kennis niet volstaat. Daarna pas aanvullende tools.

### get_instructions
- Beschrijving: Haal instructies op op basis van de probleemomschrijving. Altijd eerst gebruiken.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/get_instructions`
- Payload (JSON):
  - `Probleemomschrijving` (string, verplicht)
- Uitspraak tijdens uitvoering: "Even kijken.."
- Uitspraak na uitvoering: ja

### pd_nr_check
- Beschrijving: Controleer het automaatnummer en verifieer de locatie.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/locatie_informatie`
- Payload (JSON):
  - `pd_nr` (object, verplicht):
    - `value` (integer), `type` ("integer"), `minimum` (1000), `maximum` (2029)
- Uitspraak tijdens uitvoering: "Uhm"
- Uitspraak na uitvoering: ja

### solution_path_flow
- Beschrijving: Haal oplossingen op voor problemen van de beller.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/solution_path_flow`
- Payload (JSON):
  - `pd_nr` (integer, verplicht)
  - `Probleemomschrijving` (string, verplicht)
- Uitspraak tijdens uitvoering: "Ik ga even kijken wat ik in het systeem kan vinden..."
- Uitspraak na uitvoering: ja

### transactie_controle_snel
- Beschrijving: Controleer of een transactie tijdens het gesprek is gelukt.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/transactie_controle_snel`
- Payload (JSON):
  - `pd_nr` (object, verplicht): wrapper met `value`, `type`, `minimum`, `maximum`
- Uitspraak tijdens uitvoering: "Even kijken."
- Uitspraak na uitvoering: ja

### transactie_checker
- Beschrijving: Controleer of er transacties zijn geweest op een automaat.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/laatste_transacties`
- Payload (JSON):
  - `pd_nr` (number)
- Uitspraak na uitvoering: ja

### status_checker
~~vervangen door solution_path_flow en specifieke status‑routes in N8N~~

### automaat_in_de_buurt
- Beschrijving: Vind een alternatieve, werkende automaat in de buurt.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/automaat-in-de-buurt`
- Payload (JSON):
  - `pd_nr` (number)
- Uitspraak tijdens uitvoering: "Ik zoek even een automaat in de buurt"
- Uitspraak na uitvoering: ja

### parkeerhulp
- Beschrijving: Hulpfunctie voor stap‑voor‑stap kaartje kopen.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/parkeer_hulp`
- Payload (JSON):
  - `pd_nr` (object, verplicht): wrapper met `value`, `type`, `minimum`, `maximum`
- Uitspraak tijdens uitvoering: "Ik haal even de juiste instructies op."
- Uitspraak na uitvoering: ja

### stuur_lokatie_sms
- Beschrijving: Verstuur een sms met de locatie van een werkende automaat.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/sms_lokatie_informatie`
- Payload (JSON):
  - `pd_nr` (object, verplicht): wrapper met `value`, `type`, `minimum`, `maximum`
- Uitspraak na uitvoering: ja

### gemeente_bezwaar
- Beschrijving: Verstuur sms met bezwaar‑informatie.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/bezwaar-gemeente`
- Payload (JSON):
  - `klant_id` (number, default 1000435)
- Uitspraak tijdens uitvoering: "Ik type even de sms."
- Uitspraak na uitvoering: ja

### transfer_call
- Beschrijving: Zet het gesprek door naar een medewerker na bevestiging.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/transfer_call`
- Parameters:
  - `reden` (string, optioneel)
- Uitspraak tijdens uitvoering: "Ik verbind u nu door..."
- Uitspraak na uitvoering: n.v.t.

### end_call
- Beschrijving: Beëindig het gesprek wanneer er geen verdere vragen zijn.
- Methode: POST
- Endpoint: `https://henk.taxameter.nl/webhook/end_call`
- Parameters: geen
- Uitspraak tijdens uitvoering: "Fijne dag en tot ziens."
- Uitspraak na uitvoering: n.v.t.

### press_digit (DTMF‑invoer)
- Beschrijving: Laat de beller vier cijfers intoetsen en afsluiten met '#'. Dit is geen webhook; invoer wordt door de telephony‑laag (DTMF) opgevangen en doorgegeven aan het LLM.
- Methode: n.v.t. (telephony event)
- Endpoint: n.v.t.
- Parameters: n.v.t.
- Uitspraak tijdens uitvoering: "Toets nu het viercijferige nummer in en sluit af met een hekje."
- Uitspraak na uitvoering: spreek de ontvangen cijfers hardop uit, cijfer voor cijfer.


