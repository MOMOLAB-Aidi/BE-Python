from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from sqlalchemy.orm import sessionmaker

from app.core.db import get_engine
from app.services.kdigo_preprocess import build_kdigo_chunks

BASE_DIR = Path(__file__).resolve().parent.parent
PDF_FILES = [
    BASE_DIR / "data" / "kdigo_bp_guideline_2021.pdf",
    BASE_DIR / "data" / "kdigo_ckd_top10_takeaways_2024.pdf",
    BASE_DIR / "data" / "kdigo_diabetes_ckd_top10_2022.pdf",
]

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def main():
    all_docs = []

    # 1. 여러 PDF 로드해서 한꺼번에 텍스트로 모으기
    for pdf_path in PDF_FILES:
        if not pdf_path.exists():
            print(f"[경고] PDF 파일을 찾을 수 없습니다: {pdf_path}")
            continue

        print(f"[INFO] PDF 로딩 중: {pdf_path}")
        loader = PyPDFLoader(str(pdf_path))
        docs = loader.load()
        all_docs.extend(docs)

    if not all_docs:
        print("[ERROR] 로드된 PDF 문서가 없습니다. PDF 경로를 확인하세요.")
        return

    # LangChain Document 리스트 → 하나의 큰 텍스트로 합치기
    kdigo_text = "\n\n".join(doc.page_content for doc in all_docs)

    # 2. DB 세션 열기
    db = SessionLocal()
    try:
        # 3. 청크 + 임베딩 + DB 저장
        count = build_kdigo_chunks(db, kdigo_text, clear_existing=True)
        print(f"[완료] {count}개 KDIGO 청크가 저장되었습니다.")
    finally:
        db.close()


if __name__ == "__main__":
    main()