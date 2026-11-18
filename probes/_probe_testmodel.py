import time, json, sys
t0 = time.time()
import pydantic_ai
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
t1 = time.time()
print("import pydantic_ai ms =", int((t1 - t0) * 1000))

from pydantic import BaseModel, Field
from dataclasses import dataclass

class Out(BaseModel):
    reply: str
    picks: list[str] = Field(default_factory=list)

@dataclass
class Deps:
    rows: list

agent = Agent("test", output_type=Out, deps_type=Deps, instructions="x")

@agent.tool
def search(ctx, terms: list[str]) -> list[str]:
    """search"""
    return ["a", "b"]

t2 = time.time()
with agent.override(model=TestModel(custom_output_args={"reply": "hi", "picks": ["a"]})):
    res = agent.run_sync("q", deps=Deps(rows=[]))
print("testmodel override ok =", res.output.model_dump(), "ms =", int((time.time() - t2) * 1000))
print("requests =", res.usage.requests, "tool_calls =", res.usage.tool_calls)
