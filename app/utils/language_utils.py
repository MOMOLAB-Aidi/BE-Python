# 텍스트에 한국어가 포함되어 있는지 확인
# 한국어가 하나라도 포함되어 있으면 True, 아니면 False
def is_korean(text: str) -> bool:
    return any(
        '가' <= ch <= '힣' or
        'ㄱ' <= ch <= 'ㅎ' or
        'ㅏ' <= ch <= 'ㅣ'
        for ch in text
    )