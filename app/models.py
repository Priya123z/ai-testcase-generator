from pydantic import BaseModel, Field
from typing import List


class GherkinStep(BaseModel):
    keyword: str = Field(..., description="Given/When/Then/And")
    text: str


class GherkinScenario(BaseModel):
    name: str
    steps: List[GherkinStep]
    tags: List[str] = Field(default_factory=list)


class PytestStep(BaseModel):
    description: str
    code: str


class PytestTestCase(BaseModel):
    function_name: str
    docstring: str
    steps: List[PytestStep]


class TestSuite(BaseModel):
    # Not a test class, despite the name. pytest collects anything matching Test*
    # that it finds in a test module's namespace, and warned about this one on
    # every single run: "cannot collect test class 'TestSuite'". This is the flag
    # pytest documents for saying so.
    __test__ = False

    feature: str = Field(..., description="Feature name derived from the user story")
    scenarios: List[GherkinScenario]
    pytest_cases: List[PytestTestCase]
    coverage_notes: str = Field(..., description="Brief note on what scenarios are covered and what's intentionally out of scope")
