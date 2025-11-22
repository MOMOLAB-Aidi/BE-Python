import math
from typing import Dict, Any, Generator

from google import genai
from google.genai import types
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db_models import Record
from app.db_models.consult_log import ConsultLog, ConsultRoleEnum
from app.db_models.kdigo_chunk import kdigo_chunk

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
        return active_sessions[session_id]["user_id"] == user_id

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
        active_sessions[session_id] = {
            "user_id": user_id,
            "chat": chat,
        }
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


# RAG 로직을 위한 추가 시스템 프롬프트 정의
QUERY_REFINEMENT_SYSTEM_PROMPT = """
너는 대화 맥락을 이해하고 사용자의 질문을 독립적인 검색 쿼리로 변환하는 AI 비서야.
현재 대화 기록과 사용자의 최신 질문을 분석하여, 벡터 데이터베이스에서 가장 정확한 정보를 검색할 수 있도록
맥락이 모두 포함된 '단일의, 독립적인 검색 쿼리'만을 출력해줘.
어떠한 설명이나 추가적인 문장 없이 오직 검색 쿼리 텍스트만 출력해야 해.

[예시]
최근 기록: "어제 병원에서 혈압이 145/90이 나왔다고 했어."
환자 질문: "높은 혈압에 대해 KDIGO는 뭐라고 해?"
출력: 복막투석 환자의 고혈압 관리를 위한 KDIGO 권장사항
"""


# DB에서 최근 대화 기록을 조회하여 쿼리 정제용 문자열로 포맷팅
def get_session_history(db: Session, session_id: str, limit: int = 3) -> str:
    history_logs = db.query(ConsultLog) \
        .filter(ConsultLog.session_id == session_id) \
        .order_by(desc(ConsultLog.created_at)) \
        .limit(limit) \
        .all()

    # 순서를 오래된 것부터 최신 순으로 뒤집어 프롬프트에 사용
    formatted_history = "\n".join([
        f"{log.role.value}: {log.content}" for log in reversed(history_logs)
    ])

    return formatted_history


# LLM을 사용하여 사용자의 질문을 독립적인 검색 쿼리로 정제
def refine_query(db: Session, session_id: str, current_query: str) -> str:
    try:
        # 1. 최근 대화 기록과 현재 질문 가져오기
        history = get_session_history(db, session_id, limit=3)

        # 2. 쿼리 정제용 프롬프트 구성
        refinement_prompt = (
            f"--- 최근 대화 기록 (최대 3개) ---\n"
            f"{history}\n"
            f"--- 환자 최신 질문 ---\n"
            f"{current_query}"
        )

        # 3. 쿼리 정제 LLM 호출 (시스템 프롬프트 적용)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=refinement_prompt,
            config=types.GenerateContentConfig(
                system_instruction=QUERY_REFINEMENT_SYSTEM_PROMPT
            )
        )

        # 4. 출력에서 불필요한 공백/따옴표 제거 후 반환
        return response.text.strip().replace('"', '')

    except Exception as e:
        print(f"[Query Refinement] 오류 발생: {e}. 원본 쿼리를 대신 사용합니다.")
        return current_query  # 실패 시 원본 쿼리 반환


# 두 벡터(list[float])의 코사인 유사도 계산
def cosine_similarity(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / norm_a / norm_b


# 정제된 쿼리를 임베딩하여 벡터 DB에서 가장 관련성 높은 KDIGO 청크를 검색
def kdigo_vector_search(refined_query: str, db: Session) -> str:
    if not client:
        return "KDIGO 검색 서비스가 초기화되지 않았습니다."

    try:
        # 1. 정제된 쿼리를 벡터로 임베딩 (gemini 임베딩 모델 사용)
        embedding_result = client.embeddings.embed_content(
            model="embedding-001",
            content=refined_query
        )
        query_vector = embedding_result.embedding  # 쿼리 벡터 (리스트 형태)

        # 2. DB에서 KDIGO 청크 + 임베딩 전부 가져오기
        #    (kdigo_chunk.embedding 은 JSONB/ARRAY 로 저장된 list[float] 이라고 가정)
        chunks = db.query(kdigo_chunk).all()

        scored = []
        for c in chunks:
            if not c.embedding:
                continue
            score = cosine_similarity(query_vector, c.embedding)
            scored.append((score, c.content))

        # 3. 유사도 기준으로 정렬 (내림차순: 높을수록 유사)
        scored.sort(key=lambda x: x[0], reverse=True)

        # 4. Top-k + threshold 적용
        TOP_K = 5
        THRESHOLD = 0.3

        top_contents = [
            content
            for score, content in scored
            if score >= THRESHOLD
        ][:TOP_K]

        if not top_contents:
            return "KDIGO 가이드라인에서 해당 질문과 관련된 구체적인 지침을 찾지 못했습니다."

        kdigo_context = "\n".join([f"- {content}" for content in top_contents])
        return f"--- KDIGO 가이드라인 (검색 근거) ---\n{kdigo_context}"

    except Exception as e:
        # DB 연결, 임베딩 실패 등의 예외 처리
        print(f"[Vector Search] 오류 발생: {e}")
        return "KDIGO 검색 중 기술적인 오류가 발생했습니다."


# RAG 로직을 적용하고, 스트리밍 방식으로 응답을 생성 및 전송
def get_agent_response_stream(db: Session, user_id: int, session_id: str, message: str) -> Generator[str, None, None]:
    if client is None:
        yield "서비스가 초기화되지 않았습니다. API 키 설정을 확인해주세요."
        return

    chat_session = active_sessions.get(session_id)
    if chat_session is None:
        yield "세션이 활성화되지 않았습니다. 세션 ID를 확인하거나 세션을 새로 시작해주세요."
        return

    # DB 트랜잭션 시작 (로그 저장을 위해 사용)
    try:
        # 1. 쿼리 정제 및 KDIGO 검색 (RAG)
        # 1-1. 대화 맥락을 기반으로 쿼리 정제
        refined_query = refine_query(db, session_id, message)

        # 1-2. 정제된 쿼리로 KDIGO 벡터 DB 검색 수행
        kdigo_context = kdigo_vector_search(refined_query, db)

        # 1-3. 환자 기록 조회
        patient_records_text = get_patient_records_summary(db, user_id)

        # 2. AI 모델에 전달할 최종 RAG 프롬프트 구성
        full_message = (
            f"--- 환자 최신 기록 ---\n"
            f"{patient_records_text}\n"
            f"\n{kdigo_context}\n"  # KDIGO 검색 결과 삽입
            f"\n--- 환자 질문 ---\n"
            f"{message}"
        )

        # 3. 사용자 질문 DB 로그 저장
        user_log = ConsultLog(
            user_id=user_id,
            session_id=session_id,
            role=ConsultRoleEnum.USER,
            content=message
        )
        db.add(user_log)
        db.commit()

        # 4. 모델에게 메시지 전송 및 스트림 응답 받기 (stream --> realtime)
        stream = chat_session.send_message_stream(full_message)

        full_response_text = ""

        # 5. 스트림을 통해 응답을 실시간으로 사용자에게 전달
        for chunk in stream:
            chunk_text = chunk.text
            yield chunk_text  # 실시간 응답 전송
            full_response_text += chunk_text

        # 6. 스트림 완료 후, 전체 응답을 DB에 저장
        agent_log = ConsultLog(
            user_id=user_id,
            session_id=session_id,
            role=ConsultRoleEnum.AGENT,
            content=full_response_text  # 취합된 최종 텍스트 저장
        )
        db.add(agent_log)
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"[{session_id}] 메시지 처리 중 오류 발생: {e}")
        yield "메시지 전송 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
        return


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
