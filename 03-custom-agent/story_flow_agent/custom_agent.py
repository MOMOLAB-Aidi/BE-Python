from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from typing import AsyncGenerator
from typing_extensions import override

class StoryFlowAgent(BaseAgent):
    story_generator: LlmAgent
    critic: LlmAgent
    reviser: LlmAgent
    grammar_check: LlmAgent
    tone_check: LlmAgent

    loop_agent: LoopAgent
    sequential_agent: SequentialAgent

    model_config={"arbitrary_types_allowed": True}

    def __init__(
            self,
            name: str,
            story_generator: LlmAgent,
            critic: LlmAgent,
            reviser: LlmAgent,
            grammar_check: LlmAgent,
            tone_check: LlmAgent
    ):
        loop_agent = LoopAgent(
            name = "loop_agent",
            sub_agents = [critic, reviser],
            max_iterations = 2
        )

        sequential_agent = SequentialAgent(
            name = "sequential_agent",
            sub_agents = [grammar_check, tone_check]
        )

        sub_agents_list = [story_generator, loop_agent, sequential_agent]

        super().__init__(
            name = name,
            story_generator = story_generator,
            critic = critic,
            reviser = reviser,
            grammar_check = grammar_check,
            tone_check = tone_check,
            loop_agent = loop_agent,
            sequential_agent = sequential_agent,
            sub_agents = sub_agents_list
        )

    @override
    async def _run_async_impl(
      self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:

        # 1. 스토리 초안 생성
        async for event in self.story_generator.run_async(ctx):
            yield event

        # 2. 스토리 생성 여부 확인 (스토리가 생성되지 않으면 워크플로우를 중단)
        if 'current_story' not in ctx.session.state or not ctx.session.state['current_story']:
            return

        # 3. 스토리 비평 & 수정 반복 작업
        async for event in self.loop_agent.run_async(ctx):
            yield event

        # 4. 스토리 문법 검사 & 톤 분석 순차 작업
        async for event in self.sequential_agent.run_async(ctx):
            yield event

        # 5. 스토리 톤 분석 결과가 부정적(negative)일 경우 스토리를 재생성
        tone_check_result = ctx.session.state.get("tone_check_result")

        if tone_check_result == "negative":
            async for event in self.story_generator.run_async(ctx):
                yield event
        else:
            pass

        # 워크플로우가 종료


