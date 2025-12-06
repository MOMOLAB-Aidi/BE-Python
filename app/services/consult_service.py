import logging
import threading
from typing import Dict, Any, Generator

from fastapi import HTTPException, status
from google import genai
from google.genai import types
from sqlalchemy import desc, select, func
from sqlalchemy.orm import Session, selectinload

from app.db_models import Record, ConsultSummary
from app.db_models.consult_log import ConsultLog, ConsultRoleEnum
from app.db_models.kdigo_chunk import KdigoChunk, KDIGO_EMBED_DIM
from app.models.consult_schemas import MessageRole

session_lock = threading.RLock()

# 메모리 내 임시 세션 저장소: {session_id: chat_session_object}
# 서버가 실행되는 동안 대화 이력을 임시로 저장
active_sessions: Dict[str, Any] = {}
logger = logging.getLogger(__name__)

# 세션 별 최대 토큰 수 (전체 대화 기준)
MAX_SESSION_TOKENS = 8000

# 토큰 경고 비율 (95% 이상이면 경고)
TOKEN_WARN_RATIO = 0.95

# 한국어 포함 여부 체크 (경고 메시지 언어 선택용)
def is_korean(text: str) -> bool:
    return any(
        '가' <= ch <= '힣' or
        'ㄱ' <= ch <= 'ㅎ' or
        'ㅏ' <= ch <= 'ㅣ'
        for ch in text
    )

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
                    "token_count": 0,
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

        chat = session_data["chat"]
        user_id_verified = session_data["user_id"]
        if chat is None:
            yield "세션이 올바르게 초기화되지 않았습니다. 다시 세션을 시작해주세요."
            return

    refined_query = refine_query(db, session_id, message)
    kdigo_context = kdigo_vector_search(refined_query, db)
    patient_records_text = get_patient_records_summary(db, user_id_verified)

    full_message = (
        f"--- 환자 최신 기록 ---\n"
        f"{patient_records_text}\n"
        f"\n{kdigo_context}\n"
        f"\n--- 환자 질문 ---\n"
        f"{message}"
    )

    # 토큰 수 계산 (이번 턴 full_message 기준 + 세션 누적)
    token_count = count_session_tokens(
        session_id=session_id,
        full_prompt=full_message,
    )

    logger.info(
        f"[{session_id}] token_count={token_count}, limit={MAX_SESSION_TOKENS}"
    )

    # 토큰 기준으로 WARN/END 판단
    try:
        if token_count:
            ratio = token_count / MAX_SESSION_TOKENS

            # 1. 한도 초과 → 세션 종료 안내
            if token_count > MAX_SESSION_TOKENS:

                end_session(user_id_verified, session_id)
                logger.info(
                    f"[{session_id}] 토큰 한도 초과로 세션 자동 종료 "
                    f"(tokens={token_count}, limit={MAX_SESSION_TOKENS})"
                )

                if is_korean(message):
                    end_msg = (
                        "이번 상담 세션의 대화 길이가 충분히 길어져서 자동으로 종료되었어요. "
                        "새 상담을 시작해서 이어서 질문해 주세요."
                    )
                else:
                    end_msg = (
                        "This consultation session has reached the maximum context length "
                        "and was automatically closed. Please start a new session to continue."
                    )

                yield "[TOKEN_END]" + end_msg + "\n"
                return

            # 2. 95% 이상 → WARN chunk만 먼저 보내고 계속 진행
            elif ratio >= TOKEN_WARN_RATIO:
                if is_korean(message):
                    warn_msg = (
                        "이번 상담 세션의 대화 길이가 거의 가득 찼어요. "
                        "다음 몇 번의 답변 후 자동으로 상담이 종료될 수 있어요."
                    )
                else:
                    warn_msg = (
                        "This consultation session is nearing the maximum length. "
                        "After a few more replies, a new session may start automatically."
                    )

                yield "[TOKEN_WARN]" + warn_msg + "\n"

    except Exception as e:
        logger.error(f"[{session_id}] 토큰 한도 체크 중 오류: {e}", exc_info=True)

    # USER/AGENT 로그 + 스트리밍 진행
    full_response_text = ""
    agent_log = None
    streaming_completed = False

    try:
        # USER/AGENT 로그 저장
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
            content=""
        )
        db.add(agent_log)
        db.commit()

        # 스트리밍 시작
        stream = chat.send_message_stream(full_message)

        for chunk in stream:
            chunk_text = chunk.text
            if not chunk_text:
                continue

            full_response_text += chunk_text
            yield chunk_text

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

    # 유저별 세션 목록 + 마지막 시간만 뽑는 서브쿼리
    base_subq = (
        db.query(
            ConsultLog.session_id.label("session_id"),
            func.max(ConsultLog.created_at).label("ended_at"),
        )
        .filter(ConsultLog.user_id == user_id)
        .group_by(ConsultLog.session_id)
    ).subquery()

    # 서브쿼리에 consult_summary를 LEFT JOIN 해서 summary 같이 가져오기
    rows = (
        db.query(
            base_subq.c.session_id,
            base_subq.c.ended_at,
            ConsultSummary.summary,
        )
        .outerjoin(
            ConsultSummary,
            (ConsultSummary.user_id == user_id) &
            (ConsultSummary.session_id == base_subq.c.session_id),
        )
        .order_by(desc(base_subq.c.ended_at))
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
                "summary": r.summary,
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

    # 2. 관련 요약 삭제
    db.query(ConsultSummary).filter(
        ConsultSummary.user_id == user_id,
        ConsultSummary.session_id == session_id,
    ).delete(synchronize_session=False)

    # 3. 로그 삭제
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


# 전보(telegram) 스타일 요약 프롬프트
SUMMARY_SYSTEM_PROMPT = """
You are an AI assistant that summarizes one completed consultation session for a patient undergoing peritoneal dialysis.

[Goal]
- Produce ONE short, natural-sounding "telegram style" summary (~50–100 chars).
- Tone should be concise but not overly formal or stiff. 
- Avoid mechanical or bureaucratic expressions. Aim for a natural, smooth Korean summary.

[Content]
- Compress all patient questions into 2–3 short topic phrases (Examples. "체중 증가·부종", "혈압 관리", "식단 고민").
- Compress the agent's guidance into 1–2 short actionable phrases (Examples. "수분·염분 조절", "매일 체중 확인", "의료진과 조율").
- The final sentence should follow this pattern: "[patient topics], [main guidance/조언]."
- Keep wording compact but readable; avoid overly scientific tone unless necessary.

[Style Rules]
- Language MUST match the main language of the conversation.
- Output MUST be: 
  - a single sentence
  - 50–120 characters ideally (minimum 50)
  - no greetings, no politeness, no emoji
  - no quotation marks, no bullet points, no line breaks
- Use comma-based, telegraphic style typical of Korean telegram summaries.
- Keep it natural and fluid (e.g., “~고민”, “~조언”, “~확인”, “~조율” 등).

[Examples]
- “체중·부종·식단 고민, 수분·염분 줄이고 매일 체중 확인하며 치료 방향 조율”
- “혈압·운동·수분 섭취 문의, 혈압 기록·수분 제한·운동 강도는 의료진과 조율”
"""

# 특정 세션의 전체 상담 내용을 50~100자 전보 스타일로 요약
# 환자 질문은 2~3개 주제 토픽으로, 에이전트 답변은 1~2개 핵심 조언으로 압축
def summarize_consult_session(
    db: Session,
    user_id: int,
    session_id: str,
) -> str:
    # 이미 요약이 있는지 확인
    existing = (
        db.query(ConsultSummary)
        .filter(
            ConsultSummary.user_id == user_id,
            ConsultSummary.session_id == session_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 요약이 완료된 상담 세션입니다.",
        )

    # 대화 로그 가져오기
    logs = (
        db.query(ConsultLog)
        .filter(
            ConsultLog.user_id == user_id,
            ConsultLog.session_id == session_id,
        )
        .order_by(ConsultLog.created_at.asc())
        .all()
    )

    if not logs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 세션의 상담 기록이 없습니다.",
        )

    # role: content 형식으로 전체 대화 구성
    conversation_text = "\n".join(
        f"{(log.role.value if hasattr(log.role, 'value') else log.role)}: {log.content}"
        for log in logs
    )

    if client is None:
        # 첫 100자를 잘라서 반환
        text = conversation_text.replace("\n", " ")
        return (text[:100] + "...") if len(text) > 100 else text

    try:
        # 요약 생성 프롬프트
        prompt = (
            "Summarize the following consultation between a patient and an AI agent into ONE telegram-style line.\n"
            "- Compress all patient questions into 2–3 short topic phrases (Examples. 'weight gain and swelling', 'blood pressure control').\n"
            "- Compress the agent's answers into 1–2 short phrases describing the main guidance.\n"
            "- Use the main language of the conversation (Korean or English).\n"
            "- The summary MUST be at least 50 characters long and ideally within 100–120 characters in total,\n"
            "  with no greetings, no politeness, no emoji, no quotation marks, no bullet points, no line breaks.\n"
            "- Prefer dense, comma-separated phrases rather than a polite full sentence.\n\n"
            "--- Conversation ---\n"
            f"{conversation_text}\n"
        )

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SUMMARY_SYSTEM_PROMPT
            )
        )

        summary_text = (resp.text or "").strip()
        summary_text = " ".join(summary_text.split())

        # 50자 미만이면 한 번 더 요청
        if len(summary_text) < 50:
            try:
                refine_prompt = (
                    "The following summary is too short. Rewrite it as ONE telegram-style line "
                    "with at least 50 and at most about 120 characters, keeping the same meaning.\n"
                    "- No greetings, no politeness, no emoji, no quotation marks, no bullet points, no line breaks.\n"
                    "- Use compact, comma-separated phrases instead of a polite full sentence.\n\n"
                    f"Original summary:\n{summary_text}"
                )

                refine_resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=refine_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SUMMARY_SYSTEM_PROMPT
                    )
                )

                refined = (refine_resp.text or "").strip()
                refined = " ".join(refined.split())

                if len(refined) >= 50:
                    summary_text = refined
            except Exception as refine_err:
                logger.error(f"[{session_id}] 요약 길이 보정 중 오류: {refine_err}", exc_info=True)

    except Exception as e:
        logger.error(f"[{session_id}] 상담 요약 생성 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="상담 요약 생성 중 오류가 발생했습니다.",
        ) from e

    try:
        # DB에 저장
        summary_row = ConsultSummary(
            user_id=user_id,
            session_id=session_id,
            summary=summary_text,
        )
        db.add(summary_row)
        db.commit()
        db.refresh(summary_row)

        return summary_row.summary
    except Exception as e:
        db.rollback()
        logger.error(f"[{session_id}] 요약 저장 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="상담 요약 저장 중 오류가 발생했습니다.",
        ) from e


# 이번 턴에 LLM에 전달할 전체 프롬프트의 토큰 수를 계산하고,
# 세션별 누적 토큰(active_sessions[session_id]["token_count"])에 더해 반환
def count_session_tokens(
    session_id: str,
    full_prompt: str,
) -> int:

    if client is None:
        return 0

    try:
        # 이번 턴에 보낼 프롬프트에 대한 토큰 수
        resp = client.models.count_tokens(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )

        new_tokens = getattr(resp, "total_tokens", None)
        if new_tokens is None and hasattr(resp, "usage_metadata"):
            new_tokens = getattr(resp.usage_metadata, "total_token_count", None)

        if new_tokens is None:
            logger.warning(
                f"[{session_id}] 토큰 카운트 응답에서 total_tokens를 찾지 못했습니다. resp={resp!r}"
            )
            new_tokens = 0

    except Exception as e:
        logger.error(
            f"[{session_id}] 토큰 카운트 중 오류 발생: {e}",
            exc_info=True,
        )
        # 오류 시에는 기존 누적 토큰만 그대로 반환
        with session_lock:
            session_data = active_sessions.get(session_id) or {}
            return int(session_data.get("token_count", 0))

    # 정상적으로 new_tokens를 구한 경우 → 세션 캐시에 누적
    with session_lock:
        session_data = active_sessions.get(session_id) or {}
        prev_tokens = int(session_data.get("token_count", 0))
        total = prev_tokens + int(new_tokens)
        session_data["token_count"] = total
        active_sessions[session_id] = session_data

    return total