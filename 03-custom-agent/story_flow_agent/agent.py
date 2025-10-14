from google.adk.agents import LlmAgent
from .custom_agent import StoryFlowAgent

TOPIC = "미래의 세계"
story_generator = LlmAgent(
    name = "story_generator",
    model = "gemini-2.0-flash",
    instruction = f"""
    당신은 스토리 작가입니다.
    사용자가 제공한 '주제 : {TOPIC}'를 기반으로 100단어 정도의 짧은 스토리를 작성하세요.
    """,
    output_key = "current_story"
)

critic = LlmAgent(
    name = "critic",
    model = "gemini-2.0-flash",
    instruction = """
    당신은 스토리 비평가 입니다. 세션 상태에서 'current_story'로 제공된 스토리를 리뷰하고,
    스토리를 개선할 수 있는 1~2문자의 건설적인 비평을 제공하세요.
    줄거리나 캐릭터에 집중하세요.
    """,
    output_key = "criticism"
)

reviser = LlmAgent(
    name = "reviser",
    model = "gemini-2.0-flash",
    instruction = """
    당신은 스토리 수정자 입니다. 세션 상태에서 'criticism'에 기반해 'current_story'를 수정하세요.
    수정된 스토리만 출력하세요.
    """,
    output_key = "current_story"
)

grammar_check = LlmAgent(
    name = "grammar_check",
    model = "gemini-2.0-flash",
    instruction = """
    당신은 문법 검사기 입니다. 세션 상태에서 'current_story'로 제공된 스토리의 문법을 검사하고, 수정 사항을 제시하세요.
    오류가 없으면 'Grammar is good!"을 출력하세요
    """,
    output_key = "grammar_suggestions"
)

tone_check = LlmAgent(
    name = "tone_check",
    model = "gemini-2.0-flash",
    instruction = """
    당신은 톤 분석가 입니다. 세션 상태에서 'current_story'로 제공된 스토리의 톤을 분석하고, 다음 중 하나의 단어만 출력하세요:
    'positive' (긍정적), 'negative' (부정적)
    """,
    output_key = "tone_check_result"
)

root_agent = StoryFlowAgent(
    name = "story_flow_agent",
    story_generator = story_generator,
    critic = critic,
    reviser = reviser,
    grammar_check = grammar_check,
    tone_check = tone_check
)