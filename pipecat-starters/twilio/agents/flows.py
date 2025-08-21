import os
from typing import Any, Dict, Optional

try:
    # Deze imports worden bij installatie van pipecat-flows gevalideerd
    from pipecat_flows import (  # type: ignore
        FlowManager,
        NodeConfig,
        ContextStrategy,
        FlowsFunctionSchema,
    )
except Exception:  # pragma: no cover - fallback tijdens dev zonder dependency
    FlowManager = object  # type: ignore
    class ContextStrategy:  # type: ignore
        APPEND = "APPEND"
        RESET = "RESET"
        RESET_WITH_SUMMARY = "RESET_WITH_SUMMARY"

    class NodeConfig:  # type: ignore
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FlowsFunctionSchema:  # type: ignore
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


def create_initial_node(system_prompt_text: str, respond_immediately: bool = False) -> "NodeConfig":
    role_messages = [
        {"role": "system", "content": system_prompt_text},
    ]

    return NodeConfig(
        name="initial_language_check",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "Luister eerst. Detecteer of de beller Nederlands of Engels spreekt op basis van de eerste utterance."
                    " Indien Engels, schakel naadloos over naar Engels in alle antwoorden en markeer state.language='en'."
                    " Indien Nederlands, blijf in het Nederlands en markeer state.language='nl'. Antwoord niet in deze node."
                ),
            }
        ],
        role_messages=role_messages,
        functions=[],
        context_strategy=ContextStrategy.RESET,
        respond_immediately=respond_immediately,
        pre_actions=[],
        post_actions=[],
    )


def create_problem_understanding_node() -> "NodeConfig":
    return NodeConfig(
        name="problem_understanding",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "Begrijp het probleem. Stel korte, gerichte vragen. Als het in de kennisbank valt: beantwoord direct."
                ),
            }
        ],
        functions=[],  # Alleen conversatie; tools in vervolg-nodes
        context_strategy=ContextStrategy.APPEND,
        pre_actions=[],
        post_actions=[],
    )


def create_general_cases_node() -> "NodeConfig":
    get_instructions_fn = FlowsFunctionSchema(
        name="get_instructions",
        description="Haal instructies voor algemene cases op.",
        properties={"Probleemomschrijving": {"type": "string"}},
        required=["Probleemomschrijving"],
    )

    return NodeConfig(
        name="general_cases",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "Roep get_instructions aan indien niet in kennisbank. Leg de beller kort uit wat je doet (pre), en bevestig na afloop (post)."
                ),
            }
        ],
        functions=[get_instructions_fn],
        context_strategy=ContextStrategy.APPEND,
        pre_actions=[{"type": "say", "text": "Ik ga de instructies voor u ophalen."}],
        post_actions=[{"type": "say", "text": "Ik heb de instructies gevonden."}],
    )


def create_machine_specific_node() -> "NodeConfig":
    pd_nr_check_fn = FlowsFunctionSchema(
        name="pd_nr_check",
        description="Controleer automaatnummer en locatie.",
        properties={"pd_nr": {"type": "integer"}},
        required=["pd_nr"],
    )
    solution_path_flow_fn = FlowsFunctionSchema(
        name="solution_path_flow",
        description="Haal oplossingsstappen op voor een specifiek automaatprobleem.",
        properties={"pd_nr": {"type": "integer"}, "Probleemomschrijving": {"type": "string"}},
        required=["pd_nr", "Probleemomschrijving"],
    )

    return NodeConfig(
        name="machine_specific",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "Vraag om het automaatnummer (spraak of DTMF). Valideer met pd_nr_check. Roep daarna solution_path_flow aan."
                ),
            }
        ],
        functions=[pd_nr_check_fn, solution_path_flow_fn],
        context_strategy=ContextStrategy.APPEND,
        pre_actions=[{"type": "say", "text": "Een ogenblik, ik controleer de automaat."}],
        post_actions=[{"type": "say", "text": "Laten we de stappen doorlopen."}],
    )


def create_machine_help_node() -> "NodeConfig":
    parkeerhulp_fn = FlowsFunctionSchema(
        name="parkeerhulp",
        description="Hulp bij bediening automaat; vraagt om pd_nr en geeft instructies.",
        properties={"pd_nr": {"type": "integer"}},
        required=["pd_nr"],
    )
    return NodeConfig(
        name="machine_help",
        task_messages=[
            {
                "role": "system",
                "content": "Vraag om automaatnummer en roep parkeerhulp aan; lees kernstappen voor.",
            }
        ],
        functions=[parkeerhulp_fn],
        context_strategy=ContextStrategy.APPEND,
        pre_actions=[{"type": "say", "text": "Ik ga u stap voor stap helpen."}],
        post_actions=[],
    )


def create_human_handover_node() -> "NodeConfig":
    transfer_call_fn = FlowsFunctionSchema(
        name="transfer_call",
        description="Draag het gesprek over naar een menselijke medewerker.",
        properties={
            "phone_number": {"type": "string", "description": "Telefoonnummer van de agent"},
            "summary": {"type": "string", "description": "Samenvatting van het probleem"},
            "pd_nr": {"type": "integer", "description": "Automaatnummer indien bekend"},
            "location": {"type": "string", "description": "Locatie van de automaat indien bekend"},
        },
        required=["phone_number", "summary"],
    )
    
    terugbelverzoek_fn = FlowsFunctionSchema(
        name="terugbelverzoek",
        description="Registreer een terugbelverzoek als overdracht mislukt.",
        properties={
            "telefoonnummer": {"type": "string", "description": "Telefoonnummer van de beller"},
            "naam": {"type": "string", "description": "Voornaam van de beller"},
            "achternaam": {"type": "string", "description": "Achternaam van de beller"},
            "pd_nr": {"type": "integer", "description": "Automaatnummer indien bekend"},
            "samenvatting": {"type": "string", "description": "Samenvatting van het probleem"},
        },
        required=["telefoonnummer", "naam", "achternaam", "samenvatting"],
    )
    
    return NodeConfig(
        name="human_handover",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "De beller heeft gevraagd om met een menselijke medewerker te spreken. "
                    "Bevestig eerst: 'Begrijp ik goed dat u een collega wilt spreken?' "
                    "Na bevestiging: "
                    "1. Leg uit dat je het gesprek gaat overdragen. "
                    "2. Verzamel een korte samenvatting van het probleem als je die nog niet hebt. "
                    "3. Roep transfer_call aan met de samenvatting en beschikbare informatie. "
                    "4. Als de transfer mislukt, bied aan om een terugbelverzoek te registreren. "
                    "Vraag dan om naam, achternaam en telefoonnummer van de beller."
                ),
            }
        ],
        functions=[transfer_call_fn, terugbelverzoek_fn],
        context_strategy=ContextStrategy.APPEND,
        pre_actions=[],
        post_actions=[],
    )


def create_finalize_node() -> "NodeConfig":
    rapportage_fn = FlowsFunctionSchema(
        name="rapportage_tool",
        description="Stuur transcriptie + call_id naar rapportage endpoint; wacht niet op respons.",
        properties={},
        required=[],
    )
    return NodeConfig(
        name="finalize",
        task_messages=[{"role": "system", "content": "Rond af en bedank."}],
        functions=[rapportage_fn],
        context_strategy=ContextStrategy.RESET_WITH_SUMMARY,
        pre_actions=[],
        post_actions=[{"type": "hangup"}],
    )


def build_flow_nodes(system_prompt_text: str) -> Dict[str, "NodeConfig"]:
    return {
        "initial": create_initial_node(system_prompt_text),
        "understand": create_problem_understanding_node(),
        "general": create_general_cases_node(),
        "machine_specific": create_machine_specific_node(),
        "machine_help": create_machine_help_node(),
        "human_handover": create_human_handover_node(),
        "finalize": create_finalize_node(),
    }


