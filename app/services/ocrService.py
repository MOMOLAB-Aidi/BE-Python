import io
import os
import re
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import cv2
import numpy as np
import pytesseract


# ✅ Tesseract 경로 고정
_TESS_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(_TESS_EXE):
    pytesseract.pytesseract.tesseract_cmd = _TESS_EXE
    # 한글 데이터 경로 지정
    os.environ.setdefault("TESSDATA_PREFIX", r"C:\Program Files\Tesseract-OCR\tessdata")
else:
    pass

def _auto_canny(img_gray: np.ndarray) -> np.ndarray:
    """
    자동 Canny 임계값 계산 후 에지 맵 반환.
    - 입력: 그레이스케일 이미지 (np.uint8)
    - 동작: 이미지의 중앙값을 기준으로 하/상한 임계값을 산출
    - 반환: Canny 결과 (단일 채널)
    """
    v: float = float(np.median(img_gray))
    # 반올림 후 int 캐스팅
    lower: int = int(round(max(0.0, (1.0 - 0.33) * v)))
    upper: int = int(round(min(255.0, (1.0 + 0.33) * v)))
    return cv2.Canny(img_gray, lower, upper)


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    사각형 모서리 4점을 이용해 문서를 정사각 투영 보정.
    - 입력: BGR 이미지, 꼭짓점 4점 (임의 순서)
    - 동작: 꼭짓점 정렬 → 투시변환 행렬 계산 → warp
    - 반환: 투시 보정된 이미지
    """
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect

    # 출력 크기 계산
    widthA = np.hypot(br[0] - bl[0], br[1] - bl[1])
    widthB = np.hypot(tr[0] - tl[0], tr[1] - tl[1])
    maxWidth = int(max(widthA, widthB))

    heightA = np.hypot(tr[0] - br[0], tr[1] - br[1])
    heightB = np.hypot(tl[0] - bl[0], tl[1] - bl[1])
    maxHeight = int(max(heightA, heightB))

    dst = np.array(
        [[0, 0],
         [maxWidth - 1, 0],
         [maxWidth - 1, maxHeight - 1],
         [0, maxHeight - 1]],
        dtype="float32"
    )
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def _order_points(pts: np.ndarray) -> np.ndarray:
    """
    임의 순서의 4 점을 (좌상, 우상, 우하, 좌하) 순으로 정렬.
    - 입력: shape (4,2) float32
    - 반환: 동일 shape의 정렬된 좌표
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # Top-Left
    rect[2] = pts[np.argmax(s)]  # Bottom-Right

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # Top-Right
    rect[3] = pts[np.argmax(diff)]  # Bottom-Left
    return rect


def _find_document_contour(image: np.ndarray) -> Optional[np.ndarray]:
    """
    문서(사각형) 외곽 윤곽선 추정.
    - 입력: BGR 이미지
    - 동작: 그레이스케일 → 블러 → Canny → 컨투어 중 사각형(꼭짓점 4개) 탐색
    - 반환: 꼭짓점 4개 좌표 (float32, shape (4,2)) 또는 None
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = _auto_canny(gray)

    cnts, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:10]

    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
    return None


def _preprocess_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """
    OCR 전처리 파이프라인.
    - 투시 보정(가능 시) → 그레이스케일 → 히스토그램 평활화 → 적응형 이진화 → 미디안 블러
    - 반환: 이진화된 단일 채널 이미지
    """
    quad = _find_document_contour(image_bgr)
    if quad is not None:
        image_bgr = _four_point_transform(image_bgr, quad)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 35, 11
    )
    thr = cv2.medianBlur(thr, 3)
    return thr


def run_ocr(image_data: bytes, lang: str = "kor+eng") -> Tuple[str, np.ndarray]:
    """
    업로드된 이미지 바이트를 받아 OCR 수행.
    - 입력: 이미지 바이트, 언어 코드(기본 kor+eng)
    - 동작: PIL 로드 → OpenCV BGR 변환 → 전처리 → Tesseract OCR
    - 반환: (추출 텍스트, 전처리된 이미지)
    """
    # bytes -> numpy -> OpenCV BGR
    arr = np.frombuffer(image_data, dtype=np.uint8)
    image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise ValueError("이미지 디코딩 실패: 지원하지 않는 형식이거나 손상된 파일입니다.")

    proc = _preprocess_for_ocr(image_bgr)

    # OEM 3: Default LSTM, PSM 6: 한 블록 내 텍스트
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(proc, lang=lang, config=config)
    return text, proc


def parse_pd_record_from_text(text: str) -> Dict[str, Any]:
    """
    복막투석 기록일지 OCR 텍스트를 구조화된 필드로 파싱.
    추출 대상:
      - 혈압 systolic/diastolic: 120/80
      - 시간 record_time: 08:45, 8.45, 8:45 (뒤에 한글 조사 허용)
      - 체중 weight_kg: 70.2kg, 68,3kg
      - 유출량 outflow_ml: 1500 mL, 1300mL
      - 교환회차 exchange_count: 3회차
      - 혼탁도 clarity: 맑음/탁함
      - 복통 abdominal_pain: 없음/이상
      - 주사구 exit_site: 정상/이상
      - 날짜 record_date: 2025-10-18 / 2025.10.18 → YYYY-MM-DD
    값이 없으면 일부 기본값(날짜=오늘) 보정.
    """
    patch: Dict[str, Any] = {}

    # 공백/제로폭문자 제거(간단 표준화). 줄바꿈은 공백 하나로
    t = text.replace(" ", "").replace("\u200b", "").replace("\n", " ")

    # 혈압: 120/80
    m = re.search(r'(\d{2,3})[\/](\d{2,3})', t)
    if m:
        patch["systolic"] = int(m.group(1))
        patch["diastolic"] = int(m.group(2))

    # 시간: HH:MM or H.MM (조사 허용) → record_time
    m = re.search(r'(?<!\d)([01]?\d|2[0-3])[:\.]?([0-5]\d)(?=\D|$)', t)
    if m:
        h, mi = m.groups()
        patch["record_time"] = f"{int(h):02d}:{int(mi):02d}"

    # 체중: 70.2kg / 68,3kg
    m = re.search(r'(\d{2,3}(?:[.,]\d)?)kg', t, re.IGNORECASE)
    if m:
        patch["weight_kg"] = float(m.group(1).replace(",", "."))

    # 유출량: 1500mL
    m = re.search(r'(\d{3,4})mL', t, re.IGNORECASE)
    if m:
        patch["outflow_ml"] = int(m.group(1))

    # 교환회차: 3회차
    m = re.search(r'(\d{1,2})회차', t)
    if m:
        patch["exchange_count"] = int(m.group(1))

    # 혼탁도: 맑음/탁함
    if "혼탁" in t:
        if ("맑" in t) or ("투명" in t):
            patch["clarity"] = "맑음"
        if ("탁" in t) or ("흐림" in t):
            patch["clarity"] = "탁함"

    # 복통: 없음/이상
    if "복통" in t:
        if ("없" in t) or ("아니" in t) or ("무" in t):
            patch["abdominal_pain"] = "없음"
        if ("있" in t) or ("이상" in t) or ("통증" in t):
            patch["abdominal_pain"] = "이상"

    # 주사구: 정상/이상
    if "주사구" in t:
        if ("정상" in t) or ("괜찮" in t):
            patch["exit_site"] = "정상"
        if ("이상" in t) or ("발적" in t) or ("분비" in t):
            patch["exit_site"] = "이상"

    # 날짜: 2025-10-18 또는 2025.10.18
    m = re.search(r'(20\d{2})[-\.](\d{1,2})[-\.](\d{1,2})', text)
    if m:
        y, mo, d = map(int, m.groups())
        patch["record_date"] = f"{y:04d}-{mo:02d}-{d:02d}"
    else:
        # OCR에서 날짜가 잘 안 잡히면 오늘 날짜로 보정
        patch.setdefault("record_date", datetime.now().strftime("%Y-%m-%d"))

    return patch
