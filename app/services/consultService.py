from typing import Dict, Any

from google import genai
from google.genai import types
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db_models import Record
from app.db_models.consult_log import ConsultLog, ConsultRoleEnum

# 메모리 내 임시 세션 저장소: {session_id: chat_session_object}
# 서버가 실행되는 동안 대화 이력을 임시로 저장
active_sessions: Dict[str, Any] = {}

# 에이전트의 역할과 지침 정의
SYSTEM_PROMPT = """
너는 복막투석 환자의 개별 건강 기록과 KDIGO 가이드라인을 분석하여, 데이터 기반의 구체적이고 전문적인 관리 조언을 제공하는 전문 인공지능 에이전트야.

[답변 스타일 및 형식]
1. 답변은 불필요한 서론, 감정적 표현, 대화형 안내 구문(예: '~ 알려드릴게요')을 엄격히 제외하고, 사실적이고 전문적인 정보 전달에 집중해줘.
2. 입력으로 제공된 **환자의 최신 기록 데이터**를 최우선으로 분석하고, 이를 KDIGO 가이드라인의 일반 지침과 연결하여 조언을 생성해야 해.
3. 답변은 환자가 현재 상태에서 취해야 할 구체적인 조치(예: 염분 섭취 <5g/일 유지, 유산소 활동 증가)를 제시해야 해.

[상담 및 안전 지침 - 절대 원칙]
1. 너는 의료 전문가가 아니므로 절대로 의학적 진단, 치료 계획, 약물 처방을 대체하면 안돼. 모든 답변은 **정보 제공 및 기록 분석 기반의 조언**임을 명확히 밝혀야 해.
2. 환자가 심각하거나 급작스러운 증상을 호소할 경우, 즉시 담당 의료진에게 연락하거나 응급실을 방문하도록 강력하게 권고해야 해.
3. 기존 약물 처방이나 투석 계획의 변경을 직접적으로 조언해서는 안돼. 모든 변경 사항은 의료진과 상의하도록 지시해줘.

[입력 데이터 처리 지침]
1. 질문 내용과 가장 관련 있는 항목(예: 질문이 '붓기'면 체중, 제수량, 혈압 기록)을 집중적으로 분석하여 조언에 반영해줘.
2. 답변의 근거는 KDIGO 환자용 가이드라인(식단, 운동, 약물, 혈압 등) 내의 정보를 사용해줘.
"""

# gemini 클라이언트 초기화
client = None
try:
    client = genai.Client()
    print("gemini 클라이언트가 성공적으로 초기화되었습니다.")
except Exception:
    print("gemini 클라이언트 초기화에 실패하였습니다.")


# 새로운 채팅 세션을 생성하고 메모리에 저장
def start_new_session(user_id: int, session_id: str) -> bool:
    if client is None:
        return False

    if session_id in active_sessions:
        # 기존 세션이 있다면, 요청한 user_id가 소유자와 일치하는지 확인
        if active_sessions[session_id].get('user_id') != user_id:
            return False # 소유자가 다르면 세션 시작 불가
        return True

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
        print(f"[{session_id}] 새로운 대화 시작 실패: {e}")
        return False


# 특정 세션 ID의 활성화 상태를 확인
def get_session_status(user_id: int, session_id: str) -> bool:
    session_data = active_sessions.get(session_id)
    if session_data is None:
        return False
    # 세션이 존재하고, 요청한 user_id가 세션 소유자와 일치하는 경우 True 반환
    return session_data.get('user_id') == user_id


# 환자의 최신 복막투석 및 건강 기록을 조회하여 문자열로 포맷팅
def get_patient_records_summary(db: Session, user_id: int) -> str:

    # 최신 기록 하나 조회
    latest_record = db.query(Record).filter(Record.user_id == user_id).order_by(desc(Record.record_date)).first()

    if not latest_record:
        return "최신 복막투석 및 건강 기록을 찾을 수 없습니다."

    # 데이터 포맷팅
    exchange_details = "\n".join([
        f"- 회차 {ex.exchange_no}: 시각={ex.exchange_time.strftime('%H:%M')}, 주입액={ex.fill_concentration}%, 제수량={ex.uf}g"
        for ex in latest_record.exchanges
    ])

    summary = (
        f"--- 환자 최신 복막투석 기록 ---\n"
        f"기록 날짜: {latest_record.record_date.strftime('%Y-%m-%d')} ({latest_record.record_dw.value})\n"
        f"체중: {latest_record.weight:.1f} kg\n"
        f"혈압: {latest_record.systolic}/{latest_record.diastolic} mmHg\n"
        f"공복 혈당: {latest_record.fasting_glucose} mg/dL\n"
        f"소변 횟수: {latest_record.urine_count} 회\n"
        f"복막액 혼탁: {latest_record.turbidity.value}\n"
        f"비고: {latest_record.notes or '없음'}\n"
        f"제수량 합계: {latest_record.total_uf} g\n"
        f"\n--- 회차별 투석 상세 기록 ({latest_record.record_date.strftime('%Y-%m-%d')}) ---\n"
        f"{exchange_details or '회차별 상세 기록 없음'}\n"
    )

    return summary

# 활성화된 세션을 사용하여 gemini 모델에 메시지를 보내고 응답 받는 로직
def get_agent_response(db: Session, user_id: int, session_id: str, message: str) -> str:
    if client is None:
        return "서비스가 초기화되지 않았습니다. API 키 설정을 확인해주세요."

    chat_session = active_sessions.get(session_id)
    if chat_session is None:
        return "세션이 활성화되지 않았습니다. 세션 ID를 확인하거나 세션을 새로 시작해주세요."

    try:
        # 환자 기록 조회 및 프롬프트 조합
        patient_records_text = get_patient_records_summary(db, user_id)

        # AI 모델에 전달할 최종 메시지 구성
        # 기록이 없을 경우에도 이 텍스트가 AI에게 전달됨.
        full_message = (
            f"--- 환자 최신 기록 ---\n"
            f"{patient_records_text}\n"
            f"--- 환자 질문 ---\n"
            f"{message}"
        )

        user_log = ConsultLog(
            user_id=user_id,
            session_id=session_id,
            role=ConsultRoleEnum.USER,
            content=message
        )
        db.add(user_log)
        db.commit()

        # 2. 모델에게 메시지 전송 및 응답 받기
        response = chat_session.send_message(full_message)
        agent_response_text = response.text

        # 3. 에이전트 응답을 DB에 저장
        agent_log = ConsultLog(
            user_id=user_id,
            session_id=session_id,
            role=ConsultRoleEnum.AGENT,
            content=agent_response_text
        )
        db.add(agent_log)
        db.commit()

        return agent_response_text

    except Exception:
        db.rollback()
        return "메시지 전송 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


# 활성화된 세션을 메모리에서 제거
def end_session(user_id: int, session_id: str) -> bool:
    session_data = active_sessions.get(session_id)
    if session_data is None:
        return False

    # 사용자 ID 인증 확인
    if session_data.get('user_id') != user_id:
        print(f"[{session_id}] 세션 종료 권한 없음: 요청={user_id}, 소유자={session_data.get('user_id')}")
        return False

    # DB에 저장된 대화 기록은 유지하고, 메모리 내의 세션만 삭제
    del active_sessions[session_id]
    return True