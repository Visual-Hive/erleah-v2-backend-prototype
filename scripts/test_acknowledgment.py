import asyncio
import os
import sys
import structlog
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.middleware.logging import configure_structlog
from langchain_core.messages import HumanMessage, SystemMessage

configure_structlog()
logger = structlog.get_logger()


async def test_acknowledgment():
    print("\n" + "=" * 50)
    print("TESTING ACKNOWLEDGMENT FLOW (Grok/Groq replacement)")
    print("=" * 50)

    # 1. Check Configuration
    from src.config import settings

    print(f"USE_LLM_PROXY: {settings.use_llm_proxy}")
    if settings.use_llm_proxy:
        print(f"Target: Proxy @ {settings.llm_proxy_url} ({settings.llm_proxy_model})")
    else:
        print(f"Target: Direct Groq ({settings.groq_model})")
        print(f"Groq Key configured: {bool(settings.groq_api_key)}")

    # 2. Get Registry and Prompt
    registry = get_prompt_registry()
    llm_registry = get_llm_registry()

    node = "acknowledgment"
    llm = llm_registry.get_model(node)
    prompt = registry.get(node)

    user_message = "Hi, can you help me find the awards ceremony location?"
    user_profile = {"interests": "Technology, Networking"}

    user_content = (
        f"User message: {user_message}\nUser interests: {user_profile['interests']}"
    )

    print(f"\nUser says: '{user_message}'")
    print("Generating acknowledgment...")

    start_time = asyncio.get_event_loop().time()
    try:
        # 3. Invoke LLM
        result = await llm.ainvoke(
            [SystemMessage(content=prompt), HumanMessage(content=user_content)]
        )

        duration = asyncio.get_event_loop().time() - start_time
        print(f"\n[SUCCESS] Response received in {duration:.2f}s")
        print(f'AI Response: "{str(result.content).strip()}"')

    except Exception as e:
        print(f"\n[FAILED] Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_acknowledgment())
