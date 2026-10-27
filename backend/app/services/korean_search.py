"""Korean initial consonant (초성) search utility.

Supports searching Korean patient names by initial consonants:
  ㅎㄱㄷ → matches 홍길동
  ㄱ → matches 김, 강, 고, etc.
"""

# Korean Unicode ranges
CHOSUNG_START = 0x1100
HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3
CHOSUNG_COUNT = 19
JUNGSUNG_COUNT = 21
JONGSUNG_COUNT = 28

# Initial consonants (초성) in order
CHOSUNG_LIST = [
    'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ',
    'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
]

# Map ㄱ-ㅎ jamo characters to chosung index
JAMO_TO_CHOSUNG = {c: i for i, c in enumerate(CHOSUNG_LIST)}


def get_chosung(char: str) -> str | None:
    """Extract initial consonant from a single Korean character."""
    code = ord(char)
    if HANGUL_BASE <= code <= HANGUL_END:
        idx = (code - HANGUL_BASE) // (JUNGSUNG_COUNT * JONGSUNG_COUNT)
        return CHOSUNG_LIST[idx]
    if char in JAMO_TO_CHOSUNG:
        return char
    return None


def extract_chosung(text: str) -> str:
    """Extract initial consonants from Korean text.

    '홍길동' → 'ㅎㄱㄷ'
    'Kim' → 'Kim' (non-Korean preserved)
    """
    result = []
    for char in text:
        cs = get_chosung(char)
        result.append(cs if cs else char)
    return ''.join(result)


def is_chosung_query(query: str) -> bool:
    """Check if query consists only of Korean initial consonants."""
    return all(c in JAMO_TO_CHOSUNG or c in (' ', '^') for c in query if c.strip())


def matches_chosung(name: str, query: str) -> bool:
    """Check if a name matches a chosung query.

    matches_chosung('홍길동', 'ㅎㄱㄷ') → True
    matches_chosung('홍길동', 'ㅎㄱ') → True (prefix match)
    matches_chosung('김철수', 'ㅎㄱ') → False
    """
    if not query or not name:
        return False

    # Clean name (DICOM PN format uses ^ as separator)
    clean_name = name.replace('^', ' ').replace(',', ' ').strip()

    # Extract chosung from name
    name_chosung = extract_chosung(clean_name).replace(' ', '')
    query_clean = query.replace(' ', '')

    # Prefix match
    return name_chosung.startswith(query_clean)


def filter_by_chosung(items: list[dict], query: str, name_key: str = "PatientName") -> list[dict]:
    """Filter a list of dicts by chosung matching on a name field.

    Args:
        items: list of dicts (e.g., Orthanc study results)
        query: chosung query (e.g., 'ㅎㄱㄷ')
        name_key: key in dict to match against

    Returns:
        filtered list where name matches the chosung query
    """
    return [
        item for item in items
        if matches_chosung(str(item.get(name_key, '')), query)
    ]
