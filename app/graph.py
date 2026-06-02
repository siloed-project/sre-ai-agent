from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from app.prompts import SYSTEM_PROMPT
from app.tools_k8s import (
    get_deployment,
    get_pod,
    get_pod_logs,
    list_deployments,
    list_events,
    list_nodes,
    list_pods,
)

TOOLS = [list_pods, list_nodes, list_events, list_deployments, get_pod, get_deployment, get_pod_logs]


def build_agent(checkpointer=None):
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
    return create_react_agent(llm, TOOLS, prompt=SYSTEM_PROMPT, checkpointer=checkpointer)
