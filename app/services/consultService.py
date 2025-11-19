from typing import Dict

from google import genai
from google.genai import types

# 메모리 내 임시 세션 저장소: {session_id: chat_session_object}
# 서버가 실행되는 동안 대화 이력을 임시로 저장
active_sessions: Dict[str, genai.chats.Chat] = {}

# 에이전트의 역할과 지침 정의
SYSTEM_PROMPT = """
너는 복막투석 환자를 위한 친절하고 전문적인 상담 에이전트야.
환자들이 자주 묻는 증상, 약물 복용, 그리고 일반적으로 피해야 할 음식 성분 등에 대한 일반적이고 신뢰할 수 있는 정보를 제공할 수 있어야 해.

[답변 스타일 및 형식]
1. 최대한 간결하고 핵심적인 정보만을 담아야 하며, 불필요한 서론, 결론 및 대화형 안내 구문(예: '~ 알려드릴게요')을 엄격히 제외해줘.
2. 공감이나 따뜻한 감정을 표현하는 어조 없이, **사실적이고 전문적인 정보 전달에만 집중**해야 해.

[상담 및 안전 지침]
1. 너는 면허를 가진 의료 전문가가 아닌 **정보 제공 목적의 인공지능 에이전트**야. **절대로 사용자의 개별 증상에 대한 의학적 진단, 치료 계획 수립, 또는 약물 처방을 대체할 수 없어.**
2. 제공되는 모든 정보는 일반적인 복막투석 지침 및 지식에 기반하며, 사용자의 현재 건강 상태를 고려한 맞춤형 조언이 될 수 없어. 진단, 처방 변경, 구체적인 치료 방침 제시는 엄격히 금지.
3. 환자가 심각하거나 급작스러운 증상(예: 투석액 혼탁, 고열, 심한 통증, 급격한 부종)을 호소할 경우, **즉시 담당 의료진에게 연락하거나 응급실을 방문하도록 강력하고 명확하게 권고해야 해.**
4. 환자의 기록 데이터를 분석하거나 답변에 반영하지 말고 일반적인 지침만을 알려줘.
"""

# gemini 클라이언트 초기화
client = None
try:
    client = genai.Client()
    print("gemini 클라이언트가 성공적으로 초기화되었습니다.")
except Exception as e:
    print("gemini 클라이언트 초기화에 실패하였습니다.")


# 새로운 채팅 세션을 생성하고 메모리에 저장
def start_new_session(session_id: str) -> bool:
    if client is None:
        return False

    if session_id in active_sessions:
        # 기존 세션이 있다면 덮어쓰거나 무시
        pass

    try:

        # 시스템 프롬프트를 포함하는 GenerationConfig 객체 생성
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT
        )

        # config 객체를 전달하여 시스템 프롬프트 설정
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=config
        )
        active_sessions[session_id] = chat
        return True
    except Exception as e:
        print(f"{session_id}에 대하여 새로운 대화를 시작하는 것에 실패하였습니다.: {e}")
        return False


# 특정 세션 ID의 활성화 상태를 확인
def get_session_status(session_id: str) -> bool:
    return session_id in active_sessions


# 활성화된 세션을 사용하여 gemini 모델에 메시지를 보내고 응답 받는 로직
def get_agent_response(session_id: str, message: str) -> str:
    if client is None:
        return "서비스가 초기화되지 않았습니다. API 키 설정을 확인해주세요."

    chat_session = active_sessions.get(session_id)
    if chat_session is None:
        return "세션이 활성화되지 않았습니다. 세션 ID를 확인하거나 세션을 새로 시작해주세요."

    try:
        # 모델에게 메시지 전송 (이전 대화 이력이 자동으로 포함되어 연속성 유지)
        response = chat_session.send_message(message)
        return response.text
    except Exception:
        return "메시지 전송 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


# 활성화된 세션을 메모리에서 제거
def end_session(session_id: str) -> bool:
    if session_id in active_sessions:
        del active_sessions[session_id]
        return True
    return False