# SRE Q&A Agent

A local CLI agent that answers read-only questions about a Kubernetes cluster using Claude Haiku.

## Requirements

- Docker
- A valid `~/.kube/config` with cluster access
- An [Anthropic API key](https://console.anthropic.com)

## Build

```bash
docker build -t sre-agent .
```

## Run

```bash
docker run --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e ANTHROPIC_API_KEY=your-key-here \
  sre-agent "Which pods are unhealthy?"
```

## Example questions

```bash
docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Are any nodes under pressure?"

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Which deployments have unavailable replicas?"

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Show me recent warning events in the kube-system namespace."

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Are there any pods restarting frequently?"
```
