```bash
cd "/Users/tristanvandoorn@makerlab.nl/Documents/pipecat-cloud-images/pipecat-starters/twilio"

# Werk op de flows-branch
git checkout pipecat-flow-v01

# Commit alle relevante wijzigingen (flows, loader, TTS-switch, rapportage)
git add bot.py agents/flows.py agents/__init__.py requirements.txt README.md docs/system_prompt.md docs/tools.md docs/implementation_plan.md docs/tools_implementation_plan.md docs/commands.md flows/export.json pcc-deploy.toml Dockerfile
git commit -m "feat(flows): FlowManager integratie, JSON loader, TTS taal-switch, rapportage tool"
git push -u origin pipecat-flow-v01

# Build + push image (huidige tag staat in pcc-deploy.toml)
IMAGE_TAG="docker.io/tristanvandoorn1/twilio-agent-henk1:0.6"
docker build --platform linux/arm64 -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"

# Deploy naar Pipecat Cloud
pcc deploy

# Test-lokaal: start editor (optioneel) en gebruik export.json
# Editor lokaal draaien (apart project)
# git clone https://github.com/pipecat-ai/pipecat-flows.git
# cd pipecat-flows/editor && npm install && npm run dev
# Open http://localhost:5173, exporteer flow naar twilio/flows/export.json en bel je Twilio nummer
```
