from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic

from app.prompts import SYSTEM_PROMPT
from app.tools_k8s import (
    get_deployment,
    get_pod,
    list_deployments,
    list_events,
    list_nodes,
    list_pods,
)

TOOLS = [list_pods, list_nodes, list_events, list_deployments, get_pod, get_deployment]


def build_agent():
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
    return create_agent(llm, TOOLS, system_prompt=SYSTEM_PROMPT)
