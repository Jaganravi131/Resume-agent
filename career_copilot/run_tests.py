"""Standalone test runner that bypasses the ADK agent import."""
import sys
import os
import types

# Mock google.adk so agent.py can import without the real SDK
# This must happen before importing any career_copilot module,
# because career_copilot/__init__.py imports career_copilot/agent.py.
try:
    import google
except ImportError:
    google = types.ModuleType("google")
    sys.modules["google"] = google

if not hasattr(google, "adk"):
    adk_mod = types.ModuleType("google.adk")
    adk_mod.agents = types.ModuleType("google.adk.agents")
    adk_mod.agents.llm_agent = types.ModuleType("google.adk.agents.llm_agent")
    
    class _MockAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    adk_mod.agents.llm_agent.Agent = _MockAgent  # type: ignore
    
    google.adk = adk_mod  # type: ignore
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.agents"] = adk_mod.agents
    sys.modules["google.adk.agents.llm_agent"] = adk_mod.agents.llm_agent

# Set up path
workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, workspace)

# Now import the test module and run
from career_copilot.test_career_copilot import test_workflow
test_workflow()

# Reliability regression suite (hermetic: no network, no LLM)
print("\n")
from career_copilot import test_regressions
sys.exit(test_regressions.main())
