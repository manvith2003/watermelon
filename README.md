# Autonomous Platform Intelligence Agent — GitHub

Watermelon Software Recruitment Assignment submission.

## Setup

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in GITHUB_TOKEN and LLM API key (see .env.example)

# 3. Run
python main.py run "create a bug report for the login timeout issue" --repo owner/repo
python main.py memory
python main.py metrics
```

## LLM Provider

Defaults to **Groq** (free tier, fast). Set `LLM_MODEL` and the corresponding API key in `.env`. Any [litellm-supported provider](https://docs.litellm.ai/docs/providers) works.

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) — answers the three required questions.

## Demo Scenarios

See [DEMO.md](./DEMO.md) — the three live demo instructions with expected behaviour.
