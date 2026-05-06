import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from app.graph import build_agent

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m app.main "<question>"')
        sys.exit(1)

    question = sys.argv[1]

    try:
        agent = build_agent()
    except Exception as e:
        print(f"Error initializing agent: {e}")
        print("Check that your kubeconfig is available and ANTHROPIC_API_KEY is set.")
        sys.exit(1)

    result = agent.invoke({"messages": [HumanMessage(content=question)]})
    final_message = result["messages"][-1].content
    print(final_message)


if __name__ == "__main__":
    main()
