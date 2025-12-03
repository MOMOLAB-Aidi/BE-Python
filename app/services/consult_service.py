import logging
import threading
from typing import Dict, Any, Generator

from google import genai
from google.genai import types
from sqlalchemy import desc, select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db_models import Record
from app.db_models.consult_log import ConsultLog, ConsultRoleEnum
from app.db_models.kdigo_chunk import KdigoChunk, KDIGO_EMBED_DIM
from app.models.consult_schemas import MessageRole

session_lock = threading.RLock()

# 메모리 내 임시 세션 저장소: {session_id: chat_session_object}
# 서버가 실행되는 동안 대화 이력을 임시로 저장
active_sessions: Dict[str, Any] = {}
logger = logging.getLogger(__name__)

# 에이전트의 역할과 지침 정의
SYSTEM_PROMPT = """
You are an AI assistant that provides concise, factual, data-driven guidance for patients undergoing peritoneal dialysis.
Your output language must always match the user's input language.
- If the user writes in Korean, respond in Korean.
- If the user writes in English, respond in English.

[Response Style & Format]
1. Provide concise, factual, non-emotional, non-conversational guidance.
2. Analyze the patient's latest health record and focus only on data relevant to the question.
3. Do not mention KDIGO or any guideline source explicitly.
4. Provide clear, actionable lifestyle or monitoring suggestions.
5. Do NOT include medical disclaimer sentences in every response.
6. Only provide emergency guidance when appropriate (see below).

[Safety Instructions — Conditional Output Only]
Include an emergency warning only when the user describes serious or acute symptoms, such as:
- severe abdominal pain,
- breathing difficulty,
- chest discomfort,
- sudden swelling or rapid weight gain,
- marked dizziness,
- no dialysis outflow, or severely cloudy effluent.

When emergency guidance is required:
- If the user is speaking Korean, output the following message in Korean:
  "이러한 증상은 급성 문제의 가능성이 있습니다. 즉시 담당 의료진에게 연락하거나 응급실 방문이 필요할 수 있습니다."
- If the user is speaking English, output the following message in English:
  "These symptoms may indicate an acute problem. You should immediately contact your healthcare provider or go to the emergency department."

Never output these sentences unless the symptoms above are detected.

[Data Processing Rules]
1. Focus strictly on the data relevant to the user's question.
2. Do not modify dialysis prescriptions, dwell times, medication doses, or glucose concentrations.
3. Lifestyle, sodium intake, fluid balance, and symptom-related recommendations ARE allowed.
"""

# gemini 클라이언트 초기화
client = None
try:
    client = genai.Client()
    logger.info("gemini 클라이언트가 성공적으로 초기화되었습니다.")
except Exception as e:
    logger.error(f"gemini 클라이언트 초기화 실패: {e}", exc_info=True)


# 새로운 채팅 세션을 생성하고 메모리에 저장
def start_new_session(user_id: int, session_id: str) -> bool:
    if client is None:
        return False

    with session_lock:
        # 이미 세션이 있다면 소유자만 같으면 재사용
        if session_id in active_sessions:
            return active_sessions[session_id]["user_id"] == user_id

        else:
            try:
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT
                )

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
                logger.error(f"[{session_id}] 새로운 대화 시작 실패: {e}", exc_info=True)
                return False


# 특정 세션 ID의 활성화 상태를 확인
def get_session_status(user_id: int, session_id: str) -> bool:
    with session_lock:
        session_data = active_sessions.get(session_id)
        if session_data is None:
            return False
        return session_data.get("user_id") == user_id


# 환자의 최신 복막투석 및 건강 기록을 조회하여 문자열로 포맷팅
def get_patient_records_summary(db: Session, user_id: int) -> str:
    # 최신 기록 하나 조회
    latest_record = (
        db.query(Record)
        .options(selectinload(Record.exchanges))
        .filter(Record.user_id == user_id)
        .order_by(desc(Record.record_date))
        .first()
    )

    if not latest_record:
        return "최신 복막투석 및 건강 기록을 찾을 수 없습니다."

    # Enum일 수도, 그냥 문자열일 수도 있으니 안전하게 처리
    def safe_enum(v):
        return v.value if hasattr(v, "value") else v

    record_dw = safe_enum(latest_record.record_dw)
    turbidity = safe_enum(latest_record.turbidity)

    # total_uf 표시용 문자열 처리
    if latest_record.total_uf is None:
        total_uf_str = "정보 없음"
    else:
        total_uf_str = f"{latest_record.total_uf} g"

    # 데이터 포맷팅
    exchange_details = "\n".join([
        f"- 회차 {ex.exchange_no}: 시각={ex.exchange_time.strftime('%H:%M')}, 주입액={ex.fill_concentration}%, 제수량={ex.uf}g"
        for ex in latest_record.exchanges
    ])

    summary = (
        f"--- 환자 최신 복막투석 기록 ---\n"
        f"기록 날짜: {latest_record.record_date.strftime('%Y-%m-%d')} ({record_dw})\n"
        f"체중: {latest_record.weight:.1f} kg\n"
        f"혈압: {latest_record.systolic}/{latest_record.diastolic} mmHg\n"
        f"공복 혈당: {latest_record.fasting_glucose} mg/dL\n"
        f"소변 횟수: {latest_record.urine_count} 회\n"
        f"복막액 혼탁: {turbidity}\n"
        f"비고: {latest_record.notes or '없음'}\n"
        f"제수량 합계: {total_uf_str}\n"
        f"\n--- 회차별 투석 상세 기록 ({latest_record.record_date.strftime('%Y-%m-%d')}) ---\n"
        f"{exchange_details or '회차별 상세 기록 없음'}\n"
    )

    return summary


# RAG 로직을 위한 추가 시스템 프롬프트 정의
QUERY_REFINEMENT_SYSTEM_PROMPT = """
You are an AI assistant that understands the conversation context and converts the user's question into an independent search query.
Analyze the current conversation history and the user's latest question, and output a single, self-contained search query
that contains all necessary context so that the vector database can retrieve the most accurate information.

You must output only the search query text itself, with no explanations or additional sentences.

[Example]
Recent history: "Yesterday at the hospital my blood pressure was 145/90."
Patient question: "What does KDIGO say about high blood pressure?"
Output: KDIGO recommendations for managing high blood pressure in peritoneal dialysis patients
"""


def get_session_history(db: Session, session_id: str) -> str:
    # 1. DB에서 최신 순으로 3개만 가져옴
    history_logs = (
        db.query(ConsultLog)
        .filter(ConsultLog.session_id == session_id)
        .order_by(desc(ConsultLog.created_at))
        .limit(3)
        .all()
    )

    # 2. 리스트를 뒤집어서 '오래된 → 최신'으로 정렬
    history_logs = list(reversed(history_logs))

    formatted_history = "\n".join([
        f"{(log.role.value if hasattr(log.role, 'value') else log.role)}: {log.content}"
        for log in history_logs
    ])

    return formatted_history


# LLM을 사용하여 사용자의 질문을 독립적인 검색 쿼리로 정제
def refine_query(db: Session, session_id: str, current_query: str) -> str:
    try:
        # 1. 최근 대화 기록과 현재 질문 가져오기
        history = get_session_history(db, session_id)

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
        logger.error(f"[Query Refinement] 오류 발생: {e}. 원본 쿼리를 대신 사용합니다.", exc_info=True)
        return current_query  # 실패 시 원본 쿼리 반환


# 정제된 쿼리를 임베딩하여 벡터 DB에서 가장 관련성 높은 KDIGO 청크를 검색
def kdigo_vector_search(refined_query: str, db: Session) -> str:
    if not client:
        return "KDIGO 검색 서비스가 초기화되지 않았습니다."

    try:
        # 1. 정제된 쿼리를 벡터로 임베딩
        resp = client.models.embed_content(
            model="text-embedding-004",
            contents=[refined_query],  # batched input
        )
        query_vector = resp.embeddings[0].values  # 쿼리 벡터 (리스트 형태)

        if len(query_vector) != KDIGO_EMBED_DIM:
            raise RuntimeError(
                f"쿼리 임베딩 차원 불일치: {len(query_vector)} != {KDIGO_EMBED_DIM}"
            )

        # 2. pgvector 연산자를 활용한 벡터 검색
        TOP_K = 5
        stmt = (
            select(KdigoChunk.content)
            .order_by(KdigoChunk.embedding.cosine_distance(query_vector))
            .limit(TOP_K)
        )

        top_contents = db.execute(stmt).scalars().all()

        if not top_contents:
            return "KDIGO 가이드라인에서 해당 질문과 관련된 구체적인 지침을 찾지 못했습니다."

        kdigo_context = "\n".join([f"- {content}" for content in top_contents])
        return f"--- KDIGO 가이드라인 (검색 근거) ---\n{kdigo_context}"

    except Exception as e:
        # DB 연결, 임베딩 실패 등의 예외 처리
        logger.error(f"[Vector Search] 오류 발생: {e}", exc_info=True)
        return "KDIGO 검색 중 기술적인 오류가 발생했습니다."


# RAG 로직을 적용하고, 스트리밍 방식으로 응답을 생성 및 전송
def get_agent_response_stream(db: Session, user_id: int, session_id: str, message: str) -> Generator[str, None, None]:
    if client is None:
        yield "서비스가 초기화되지 않았습니다. API 키 설정을 확인해주세요."
        return

    with session_lock:
        session_data = active_sessions.get(session_id)

        if session_data is None:
            yield "세션이 활성화되지 않았습니다. 세션 ID를 확인하거나 세션을 새로 시작해주세요."
            return

        if session_data.get('user_id') != user_id:
            yield "권한이 없습니다."
            return

        # 필요한 데이터를 미리 복사
        chat = session_data["chat"]
        user_id_verified = session_data["user_id"]
        if chat is None:
            yield "세션이 올바르게 초기화되지 않았습니다. 다시 세션을 시작해주세요."
            return

    # DB 트랜잭션 시작 (로그 저장을 위해 사용)
    full_response_text = ""
    agent_log = None
    streaming_completed = False

    # 정상 종료 -> agent_log.content = full_response_text
    # 중간에 끊김 -> finally에서 "[스트리밍 중단 - 부분 응답]"이라도 채워서 저장
    try:
        # 1. 쿼리 정제 및 KDIGO 검색 (RAG)
        refined_query = refine_query(db, session_id, message)
        kdigo_context = kdigo_vector_search(refined_query, db)
        patient_records_text = get_patient_records_summary(db, user_id_verified)

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
            user_id=user_id_verified,
            session_id=session_id,
            role=ConsultRoleEnum.USER,
            content=message
        )
        db.add(user_log)
        agent_log = ConsultLog(
            user_id=user_id_verified,
            session_id=session_id,
            role=ConsultRoleEnum.AGENT,
            content=""  # 비어있는 상태로 생성(스트리밍 도중 클라이언트가 끊겨도 최소한 "이 턴에 응답을 시도했다"는 행 남기기)
        )
        db.add(agent_log)
        db.commit() # 스트리밍 완료 후 한 번에 커밋

        # 4. 스트리밍 시작
        stream = chat.send_message_stream(full_message)

        # 5. 스트림을 통해 응답을 실시간으로 사용자에게 전달
        for chunk in stream:
            chunk_text = chunk.text
            if not chunk_text:
                continue

            full_response_text += chunk_text
            yield chunk_text  # 실시간 응답 전송

        streaming_completed = True

    except Exception as e:
        db.rollback()
        logger.error(f"[{session_id}] 메시지 처리 중 오류 발생: {e}", exc_info=True)
        yield "메시지 전송 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    finally:
        if agent_log:
            try:
                if streaming_completed:
                    agent_log.content = full_response_text
                else:
                    agent_log.content = full_response_text if full_response_text else "[스트리밍 중단 — 부분 응답]"
                db.commit()
            except Exception as e:
                logger.error(f"[{session_id}] agent_log 저장 실패: {e}", exc_info=True)
                db.rollback()


# 활성화된 세션을 메모리에서 제거
def end_session(user_id: int, session_id: str) -> bool:
    with session_lock:
        session_data = active_sessions.get(session_id)
        if session_data is None:
            return False

        if session_data.get("user_id") != user_id:
            logger.warning(f"[{session_id}] 세션 종료 권한 없음: 요청={user_id}, 소유자={session_data.get('user_id')}")
            return False

        # 메모리에서만 제거 (DB 로그는 유지)
        del active_sessions[session_id]
        return True


# 특정 환자의 전체 상담 목록 조회
def get_consult_history(
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 50,
) -> list[dict]:

    base_query = (
        db.query(
            ConsultLog.session_id.label("session_id"),
            func.max(ConsultLog.created_at).label("ended_at"),
        )
        .filter(ConsultLog.user_id == user_id)
        .group_by(ConsultLog.session_id)
        .order_by(desc(func.max(ConsultLog.created_at)))
    )

    # 페이징 적용
    rows = (
        base_query
        .offset(skip)
        .limit(limit)
        .all()
    )

    result: list[dict] = []

    for r in rows:
        # 각 세션에서 환자의 첫 질문 메시지 하나 조회
        first_user = (
            db.query(ConsultLog.content)
            .filter(
                ConsultLog.user_id == user_id,
                ConsultLog.session_id == r.session_id,
                ConsultLog.role == MessageRole.USER,
            )
            .order_by(ConsultLog.created_at.asc())
            .first()
        )

        first_user_question = first_user[0] if first_user is not None else None

        result.append(
            {
                "session_id": r.session_id,
                "ended_at": r.ended_at,
                "first_user_question": first_user_question,
            }
        )

    return result

# 특정 환자의 특정 세션에 대한 USER/AGENT 대화 로그 전체를 시간순으로 조회
def get_consult_history_detail(
    db: Session,
    user_id: int,
    session_id: str,
):
    logs = (
        db.query(ConsultLog)
        .filter(
            ConsultLog.user_id == user_id,
            ConsultLog.session_id == session_id,
        )
        .order_by(ConsultLog.created_at.asc())
        .all()
    )
    return logs


# 특정 세션 상담 기록 삭제
def delete_consult_session(
    db: Session,
    user_id: int,
    session_id: str,
) -> int:
    # 1. 존재 여부 확인
    exists = (
        db.query(ConsultLog)
        .filter(
            ConsultLog.user_id == user_id,
            ConsultLog.session_id == session_id,
        )
        .first()
    )

    if not exists:
        return 0

    # 2. 있으면 삭제
    deleted_count = (
        db.query(ConsultLog)
        .filter(
            ConsultLog.user_id == user_id,
            ConsultLog.session_id == session_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count