import inspect, json
import pydantic_ai
from pydantic_ai import Agent, RunContext
print("version", getattr(pydantic_ai, "__version__", "?"))
from pydantic_ai.models.function import FunctionModel, AgentInfo
print("FunctionModel.__init__", inspect.signature(FunctionModel.__init__))
from pydantic_ai.models.test import TestModel
print("TestModel.__init__", inspect.signature(TestModel.__init__))
print("Agent.__init__", str(inspect.signature(Agent.__init__))[:600])
try:
    from pydantic_ai.models.openai import OpenAIChatModel
    print("OpenAIChatModel", inspect.signature(OpenAIChatModel.__init__))
except Exception as e:
    print("openai model import fail", e)
try:
    from pydantic_ai.providers.openai import OpenAIProvider
    print("OpenAIProvider", inspect.signature(OpenAIProvider.__init__))
except Exception as e:
    print("provider import fail", e)
try:
    from pydantic_ai.models.fallback import FallbackModel
    print("FallbackModel", inspect.signature(FallbackModel.__init__))
except Exception as e:
    print("fallback fail", e)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
print("ok messages")
from pydantic_ai.tools import Tool
print("Tool", str(inspect.signature(Tool.__init__))[:300])
