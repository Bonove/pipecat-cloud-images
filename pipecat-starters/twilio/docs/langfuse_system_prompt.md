# Stappenplan: Langfuse System Prompt Versioning integratie met Pipecat Voice Agent

## Executive Summary

Dit stappenplan beschrijft de volledige integratie van Langfuse Prompt Management voor system prompt versioning in jullie Pipecat voice agent. De implementatie maakt gebruik van Langfuse's prompt management capabilities, client-side caching, en fallback mechanismen voor productie-gereed gebruik.

## Huidige Situatie Analyse

**Bestaande setup:**
- Pipecat voice agent met OpenAI LLM service
- OpenTelemetry tracing naar Langfuse via HTTP exporter  
- Hardcoded system prompt in `messages` array
- Environment variables voor API keys en configuratie

**Gewenste situatie:**
- System prompt opgehaald uit Langfuse Prompt Management
- Versioning en labels voor prompt deployment
- Client-side caching voor lage latency
- Fallback mechanismen voor 100% beschikbaarheid

---

## Fase 1: Voorbereiding en Setup

### Stap 1.1: Environment Variables Uitbreiden

Voeg de volgende environment variables toe aan je `.env` file:

```env
# Bestaande Langfuse configuratie voor tracing
ENABLE_TRACING=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64_encoded_api_key>

# Nieuwe Langfuse configuratie voor prompt management
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=production

# Prompt management specifiek
LANGFUSE_PROMPT_NAME=pipecat-system-prompt
LANGFUSE_PROMPT_CACHE_TTL=300  # 5 minuten cache
LANGFUSE_PROMPT_FALLBACK_ENABLED=true
```

### Stap 1.2: Dependencies Installeren

Update je `requirements.txt` of installeer direct:

```bash
pip install langfuse>=3.1.0
```

**Opmerking:** Versie 3.1.0+ is vereist voor message placeholders en verbeterde prompt management features.

### Stap 1.3: Langfuse Client Initialisatie

Maak een nieuwe module `langfuse_client.py`:

```python
import os
from langfuse import Langfuse
from loguru import logger
from typing import Optional

class LangfusePromptManager:
    def __init__(self):
        self.client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
        )
        self.cache_ttl = int(os.getenv("LANGFUSE_PROMPT_CACHE_TTL", "300"))
        self.fallback_enabled = os.getenv("LANGFUSE_PROMPT_FALLBACK_ENABLED", "true").lower() == "true"
        
    def get_system_prompt(self, prompt_name: str, fallback_prompt: Optional[str] = None) -> str:
        """
        Haalt system prompt op uit Langfuse met caching en fallback
        """
        try:
            # Probeer prompt op te halen met caching
            prompt = self.client.get_prompt(
                name=prompt_name,
                label="production",  # Gebruikt altijd production label
                cache_ttl_seconds=self.cache_ttl,
                fallback=fallback_prompt if self.fallback_enabled else None
            )
            
            if prompt.is_fallback:
                logger.warning(f"Using fallback prompt for {prompt_name}")
            else:
                logger.info(f"Successfully retrieved prompt {prompt_name} (version: {prompt.version})")
            
            return prompt.prompt
            
        except Exception as e:
            logger.error(f"Failed to retrieve prompt {prompt_name}: {e}")
            if fallback_prompt:
                logger.info("Using provided fallback prompt")
                return fallback_prompt
            raise e
```

---

## Fase 2: Prompt Management Setup in Langfuse

### Stap 2.1: Initial Prompt Creation

Maak een setup script `setup_langfuse_prompts.py`:

```python
import os
from langfuse import Langfuse
from loguru import logger

def setup_initial_prompt():
    """
    Maakt de initiële system prompt aan in Langfuse
    """
    langfuse = Langfuse()
    
    # Huidige system prompt uit je bot.py
    initial_system_prompt = (
        "Je bent een behulpzame LLM in een WebRTC-gesprek genaamd Sam, de persoonlijke assistent van je collega Tristan. "
        "Je doel is om je capaciteiten op een beknopte manier te demonstreren aan Tristan en te vragen hoe je hem kunt helpen. "
        "Je output wordt omgezet naar audio, dus gebruik geen speciale tekens in je antwoorden. "
        "Antwoord altijd in het Nederlands, tenzij de gebruiker een andere taal specificeert. Reageer op wat Tristan zegt op een reatieve en behulpzame manier."
    )
    
    try:
        prompt = langfuse.create_prompt(
            name="pipecat-system-prompt",
            type="text",
            prompt=initial_system_prompt,
            labels=["production"],
            config={
                "model": "gpt-4o",
                "temperature": 0.5,
                "language": "nl",
                "voice_optimized": True
            },
            tags=["pipecat", "voice-agent", "system-prompt"]
        )
        
        logger.info(f"Created initial prompt with ID: {prompt.id}")
        return prompt
        
    except Exception as e:
        logger.error(f"Failed to create initial prompt: {e}")
        raise

if __name__ == "__main__":
    setup_initial_prompt()
```

### Stap 2.2: Prompt Versioning Strategie

**Labels systeem:**
- `production`: Actieve prompt voor productie
- `staging`: Test versie voor staging environment  
- `development`: Ontwikkel versie
- `rollback`: Backup versie voor emergency rollback

**Versioning workflow:**
1. Nieuwe prompts krijgen automatisch een versie nummer
2. Test eerst in `development` label
3. Promoot naar `staging` voor acceptatie tests
4. Deploy naar `production` na goedkeuring
5. Behoud `rollback` label op vorige productie versie

---

## Fase 3: Integratie in Pipecat Bot

### Stap 3.1: Bot.py Modificaties

**Belangrijke wijzigingen in je `bot.py`:**

```python
# Voeg toe aan imports
from langfuse_client import LangfusePromptManager

# Initialiseer prompt manager (voeg toe na load_dotenv)
prompt_manager = LangfusePromptManager()

# Pre-fetch prompt tijdens startup voor gegarandeerde beschikbaarheid
def fetch_prompts_on_startup():
    """
    Pre-fetcht prompts tijdens startup voor cache warming
    """
    try:
        fallback_prompt = (
            "Je bent een behulpzame LLM assistent genaamd Sam. "
            "Antwoord altijd in het Nederlands en houdt responses kort voor spraak."
        )
        
        system_prompt = prompt_manager.get_system_prompt(
            prompt_name=os.getenv("LANGFUSE_PROMPT_NAME", "pipecat-system-prompt"),
            fallback_prompt=fallback_prompt
        )
        
        logger.info("Successfully pre-fetched system prompt")
        return system_prompt
        
    except Exception as e:
        logger.error(f"Failed to pre-fetch prompt: {e}")
        if os.getenv("LANGFUSE_PROMPT_FALLBACK_ENABLED", "true").lower() == "true":
            logger.warning("Continuing with fallback mechanism")
        else:
            logger.critical("Exiting due to prompt fetch failure")
            sys.exit(1)

# Modificeer de run_example functie
async def run_example(transport: BaseTransport, _: argparse.Namespace, handle_sigint: bool):
    logger.info(f"Starting bot")
    
    # Pre-fetch prompt
    fetch_prompts_on_startup()

    # ... bestaande STT/TTS setup ...

    # Haal system prompt op uit Langfuse
    fallback_prompt = (
        "Je bent een behulpzame LLM assistent genaamd Sam. "
        "Antwoord altijd in het Nederlands en houdt responses kort voor spraak."
    )
    
    try:
        system_prompt_content = prompt_manager.get_system_prompt(
            prompt_name=os.getenv("LANGFUSE_PROMPT_NAME", "pipecat-system-prompt"),
            fallback_prompt=fallback_prompt
        )
    except Exception as e:
        logger.error(f"Using fallback prompt due to error: {e}")
        system_prompt_content = fallback_prompt

    # Vervang de hardcoded messages array
    messages = [
        {
            "role": "system",
            "content": system_prompt_content,
        },
    ]

    # ... rest van de functie blijft hetzelfde ...
```

### Stap 3.2: Error Handling en Resilience

**Implementeer robuuste error handling:**

```python
class PromptRetrievalError(Exception):
    """Custom exception voor prompt retrieval fouten"""
    pass

def get_system_prompt_with_retry(prompt_manager, prompt_name: str, max_retries: int = 3):
    """
    Haalt system prompt op met retry logic
    """
    for attempt in range(max_retries):
        try:
            return prompt_manager.get_system_prompt(prompt_name)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise PromptRetrievalError(f"Failed to retrieve prompt after {max_retries} attempts")
            time.sleep(2 ** attempt)  # Exponential backoff
```

---

## Fase 4: Monitoring en Observability

### Stap 4.1: Prompt Usage Tracking

**Link prompts aan tracing:**

```python
# In je LLM service call, link de prompt aan de generation
llm = OpenAILLMService(
    api_key=os.getenv("OPENAI_API_KEY"), 
    params=OpenAILLMService.InputParams(temperature=0.5)
)

# Voeg prompt metadata toe aan context
@llm.event_handler("on_llm_call_started")
async def on_llm_call_started(service, messages):
    # Link de gebruikte prompt versie aan de trace
    if hasattr(prompt_manager, 'last_used_prompt'):
        service.add_metadata({
            "prompt_name": prompt_manager.last_used_prompt.name,
            "prompt_version": prompt_manager.last_used_prompt.version,
            "prompt_labels": prompt_manager.last_used_prompt.labels
        })
```

### Stap 4.2: Performance Metrics

**Track prompt retrieval performance:**

```python
import time
from functools import wraps

def track_prompt_retrieval_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            retrieval_time = time.time() - start_time
            logger.info(f"Prompt retrieval took {retrieval_time:.3f}s")
            return result
        except Exception as e:
            retrieval_time = time.time() - start_time
            logger.error(f"Prompt retrieval failed after {retrieval_time:.3f}s: {e}")
            raise
    return wrapper
```

---

## Fase 5: Testing en Validation

### Stap 5.1: Unit Tests

**Maak test file `test_langfuse_integration.py`:**

```python
import pytest
import os
from unittest.mock import Mock, patch
from langfuse_client import LangfusePromptManager

class TestLangfusePromptManager:
    
    @pytest.fixture
    def prompt_manager(self):
        return LangfusePromptManager()
    
    @patch('langfuse_client.Langfuse')
    def test_get_system_prompt_success(self, mock_langfuse, prompt_manager):
        # Mock successful prompt retrieval
        mock_prompt = Mock()
        mock_prompt.prompt = "Test system prompt"
        mock_prompt.is_fallback = False
        mock_prompt.version = 1
        
        mock_langfuse.return_value.get_prompt.return_value = mock_prompt
        
        result = prompt_manager.get_system_prompt("test-prompt")
        assert result == "Test system prompt"
    
    @patch('langfuse_client.Langfuse')
    def test_get_system_prompt_fallback(self, mock_langfuse, prompt_manager):
        # Mock API failure with fallback
        mock_langfuse.return_value.get_prompt.side_effect = Exception("API Error")
        
        fallback = "Fallback prompt"
        result = prompt_manager.get_system_prompt("test-prompt", fallback_prompt=fallback)
        assert result == fallback
```

### Stap 5.2: Integration Tests

**Test complete workflow:**

```python
def test_complete_prompt_workflow():
    """
    Test complete workflow van prompt creation tot retrieval
    """
    # 1. Create test prompt
    # 2. Retrieve prompt 
    # 3. Verify caching
    # 4. Test fallback scenario
    pass
```

---

## Fase 6: Deployment en Rollout

### Stap 6.1: Staging Deployment

**Deployment checklist:**

1. **Environment Setup:**
   - [ ] Langfuse credentials geconfigureerd
   - [ ] Environment variables ingesteld
   - [ ] Initial prompt aangemaakt in Langfuse

2. **Code Changes:**
   - [ ] LangfusePromptManager geïmplementeerd
   - [ ] Bot.py gemodificeerd
   - [ ] Error handling toegevoegd
   - [ ] Tests geschreven en passed

3. **Monitoring Setup:**
   - [ ] Prompt retrieval metrics
   - [ ] Error alerting
   - [ ] Performance monitoring

### Stap 6.2: Production Rollout

**Rollout strategie:**

1. **Blue-Green Deployment:**
   - Deploy naar staging environment
   - Uitgebreide tests met voice interactions
   - Graduele rollout naar productie

2. **Monitoring tijdens rollout:**
   - Prompt retrieval success rate
   - Response latency impact
   - Fallback mechanism activatie

3. **Rollback procedure:**
   - Emergency fallback naar hardcoded prompt
   - Langfuse prompt label wijziging naar vorige versie

---

## Fase 7: Operationele Procedures

### Stap 7.1: Prompt Management Workflow

**Voor prompt wijzigingen:**

1. **Development:**
   ```python
   # Nieuwe prompt versie aanmaken
   langfuse.create_prompt(
       name="pipecat-system-prompt",
       prompt="Nieuwe system prompt tekst...",
       labels=["development"]
   )
   ```

2. **Testing:**
   ```bash
   # Environment variable wijzigen voor test
   export LANGFUSE_PROMPT_NAME=pipecat-system-prompt
   # Bot starten en testen
   ```

3. **Production Deployment:**
   ```python
   # Label wijzigen naar production
   langfuse.update_prompt(
       name="pipecat-system-prompt",
       version=new_version,
       new_labels=["production"]
   )
   ```

### Stap 7.2: Troubleshooting Guide

**Veelvoorkomende problemen:**

1. **Prompt niet gevonden:**
   - Controleer prompt naam en labels
   - Verificeer Langfuse credentials
   - Check network connectivity

2. **Cache issues:**
   - Verlaag cache TTL voor snellere updates
   - Force cache refresh door applicatie restart

3. **Fallback activatie:**
   - Monitor Langfuse status page
   - Check error logs voor root cause
   - Evalueer fallback prompt adequaatheid

---

## Technische Specificaties

### Caching Strategy

**Client-side caching:**
- Default TTL: 60 seconden (configureerbaar)
- Background refresh bij expired cache
- Stale-while-revalidate pattern
- In-memory storage per process

**Fallback mechanismen:**
1. Lokale cache (fresh)
2. Lokale cache (stale) + background refresh  
3. Langfuse API call
4. Fallback prompt (indien geconfigureerd)
5. Application exit (indien geen fallback)

### Performance Impact

**Expected performance:**
- First call: ~100-200ms (cold cache)
- Subsequent calls: ~1-5ms (warm cache)
- Background refresh: Asynchroon, geen user impact
- Fallback activatie: ~10-50ms

### Security Considerations

**API key management:**
- Environment variables voor credentials
- Geen hardcoded secrets in code
- Rotation procedure voor API keys
- Access logging voor audit trail

**Prompt content:**
- Geen gevoelige informatie in prompts
- Version control voor auditability
- Access control via Langfuse RBAC

---

## Conclusie en Next Steps

Deze implementatie biedt:

✅ **Volledige prompt versioning** met Langfuse Prompt Management  
✅ **Production-ready caching** voor lage latency  
✅ **Robuuste fallback mechanismen** voor 100% beschikbaarheid  
✅ **Monitoring en observability** voor operationele excellence  
✅ **Graduele rollout mogelijk** met minimaal risico  

**Aanbevolen volgorde van implementatie:**
1. Start met Fase 1-3 voor basis functionaliteit
2. Implementeer Fase 4 voor monitoring  
3. Voer Fase 5 uit voor kwaliteitsborging
4. Plan Fase 6-7 voor productie deployment



**Ondersteuning:** Gebruik Langfuse Discord community en GitHub discussions voor technische ondersteuning tijdens implementatie.