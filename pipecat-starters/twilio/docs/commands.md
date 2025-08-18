```bash
cd "/Users/tristanvandoorn@makerlab.nl/Documents/pipecat-cloud-images/pipecat-starters/twilio"

git checkout feat/bot-iteraties

# Alle relevante wijzigingen committen
git add bot.py requirements.txt README.md docs/system_prompt.md docs/tools.md docs/implementation_plan.md docs/tools_implementation_plan.md pcc-deploy.toml Dockerfile docs/commands.md
git commit -m "chore(release): prepare 0.6 (docs in image, STT=NL, tools)"
git push

# Bump image tag in pcc-deploy.toml van 0.5 naar 0.6 (let op rechte quotes)
sed -i '' 's#docker.io/tristanvandoorn1/twilio-agent-henk1:0\.5#docker.io/tristanvandoorn1/twilio-agent-henk1:0.6#' pcc-deploy.toml

git add pcc-deploy.toml
git commit -m "chore(deploy): bump image tag to 0.6"
git push

# Build + push image (platform arm64 voor Pipecat Cloud)
docker build --platform linux/arm64 -t docker.io/tristanvandoorn1/twilio-agent-henk1:0.6 .
docker push docker.io/tristanvandoorn1/twilio-agent-henk1:0.6

# Deploy
pcc deploy
```
