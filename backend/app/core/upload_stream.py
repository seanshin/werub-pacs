"""스트리밍 업로드 헬퍼 — UploadFile을 청크 단위로 디스크에 스풀 + ZIP 해제 상한.

`await file.read()`는 업로드 전체를 한 번에 RAM에 적재한다(대형 ZIP/CD는 수 GB → OOM 위험).
이 헬퍼는 1MB 청크로 디스크 임시파일에 흘려보내며 RAM 사용을 청크 크기로 고정하고,
누적 크기가 `max_bytes`를 넘으면 즉시 413으로 중단(부분 파일 정리)한다.

Body-size 미들웨어(Content-Length 백스톱)와 별개로, 실제 디스크 적재 시점의
정밀한 per-endpoint 상한을 제공한다.

**ZIP 해제 상한(v13.45)**: 위 상한들은 *유입 바이트*만 묶는다 — 압축 해제 후
팽창에는 상한이 없어서 작은 ZIP 하나가 디스크/RAM을 무제한 점유할 수 있었다.
`bounded_zip_extractall`·`bounded_zip_read`가 그 반쪽을 닫는다.
"""
import logging
import os
import tempfile
import zipfile

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1MB


async def spool_upload_to_disk(
    file: UploadFile,
    max_bytes: int,
    suffix: str = "",
    dir: str | None = None,
) -> tuple[str, int]:
    """UploadFile을 청크 단위로 디스크 임시파일에 기록.

    Returns: (임시파일 경로, 총 바이트 수)
    Raises: HTTPException(413) — 누적 크기가 max_bytes 초과 시(부분 파일 삭제 후).
            HTTPException(400) — 빈 파일.

    호출자는 사용 후 반드시 임시파일/디렉터리를 정리해야 한다.
    """
    if dir:
        os.makedirs(dir, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=dir)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        413,
                        f"파일이 너무 큽니다(최대 {max_bytes // (1024 * 1024)}MB)",
                    )
                out.write(chunk)
    except HTTPException:
        _silent_unlink(path)
        raise
    except Exception:
        _silent_unlink(path)
        raise
    finally:
        # UploadFile 핸들 정리(다음 파일 read 영향 없음 — 개별 파트)
        try:
            await file.close()
        except Exception:
            pass

    if total == 0:
        _silent_unlink(path)
        raise HTTPException(400, "빈 파일")

    return path, total


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ── ZIP 압축 해제 상한 ──────────────────────────────────────────────────────
#
# 실제 결함은 "헤더를 속일 수 있다"가 아니라 **상한이 아예 없었다**는 것이다:
# 정직하게 신고된 200MB(압축 후 199KB)짜리 멤버도 무제한 해제됐다.
#
# ★측정으로 확인한 사실(2026-08-10): CPython `zipfile.ZipExtFile`은 해제 출력을
#  신고된 `file_size`까지만 내보내고 CRC까지 검증한다 — 작게 위조한 헤더로
#  신고량보다 많이 뽑아내는 것은 이 경로에서 불가능하다(잘린 뒤 `BadZipFile`).
#  따라서 헤더 선판정은 그 자체로 유효한 상한이다.
#  그럼에도 읽은 바이트를 누적 검사하는 이유는 (a) 상한 강제 지점을 한 곳으로
#  모으고 (b) 나중에 다른 해제 경로(외부 도구·스트리밍 파서)로 바뀌어도 상한이
#  남아 있게 하려는 것 — 방어의 중복이지, 위조 대응이 아니다.


def _sanitize_zip_name(name: str) -> str | None:
    """ZIP 멤버 경로를 안전한 상대경로로 정규화. 위험/무의미하면 None.

    CPython `ZipFile.extract()`가 내부적으로 하는 정규화(드라이브·선행 구분자 제거,
    `.`/`..` 컴포넌트 제거)를 직접 수행한다 — 스트리밍 추출은 `extract()`를 쓸 수
    없으므로(상한을 걸 지점이 없다) 경로 안전은 우리 책임이 된다.
    """
    arcname = name.replace("/", os.path.sep)
    if os.path.altsep:
        arcname = arcname.replace(os.path.altsep, os.path.sep)
    arcname = os.path.splitdrive(arcname)[1]
    parts = [
        p for p in arcname.split(os.path.sep)
        if p not in ("", os.path.curdir, os.path.pardir)
    ]
    return os.path.sep.join(parts) or None


def _too_large(what: str, limit_bytes: int) -> HTTPException:
    return HTTPException(
        413,
        f"압축 해제 크기가 상한을 초과했습니다({what}, 최대 "
        f"{limit_bytes // (1024 * 1024)}MB)",
    )


def bounded_stream_to_file(
    src,
    dest_path: str,
    max_bytes: int,
    *,
    first_chunk: bytes = b"",
    label: str = "멤버",
) -> int:
    """`src`(파일류 객체)를 상한 내에서 `dest_path`에 기록. 반환: 기록한 바이트.

    RAM 사용은 청크 크기로 고정된다. 상한 초과 시 부분 파일을 지우고 413.
    `first_chunk`는 호출자가 이미 읽어 둔 선두 바이트(매직바이트 판정 등)를
    잃지 않고 이어 쓰기 위한 것 — 상한 계산에도 포함된다.

    상한 검사를 이 한 곳에 모아 둔다(호출부마다 재구현하면 갈라진다).
    """
    written = 0
    try:
        with open(dest_path, "wb") as out:
            # ★`first_chunk`가 비어 있으면 여기서 첫 청크를 읽어야 한다 — 빈 값을
            #  그대로 루프 조건에 넣으면 한 바이트도 읽지 않고 끝나 0바이트 파일이
            #  만들어진다(단위 테스트가 이 버그를 잡았다).
            chunk = first_chunk or src.read(CHUNK_SIZE)
            while chunk:
                written += len(chunk)
                if written > max_bytes:
                    raise _too_large(label, max_bytes)
                out.write(chunk)
                chunk = src.read(CHUNK_SIZE)
    except Exception:
        _silent_unlink(dest_path)
        raise
    return written


def _stream_member_to_disk(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    dest_path: str,
    max_member_bytes: int,
    max_remaining_bytes: int,
) -> int:
    """ZIP 멤버 하나를 청크 단위로 `dest_path`에 기록. 반환: 기록한 실제 바이트."""
    with zf.open(info) as src:
        return bounded_stream_to_file(
            src, dest_path,
            # 멤버 상한과 누적 잔량 중 **작은 쪽**이 실효 상한이다.
            min(max_member_bytes, max_remaining_bytes),
            label=f"멤버 {info.filename}",
        )


def bounded_zip_extractall(
    zf: zipfile.ZipFile,
    dest_dir: str,
    *,
    max_total_bytes: int,
    max_member_bytes: int,
    max_entries: int,
) -> int:
    """`ZipFile.extractall`의 상한 있는 대체. 반환: 해제한 총 바이트.

    디렉터리 구조는 원본 그대로 보존한다(DICOMDIR의 상대 경로 참조가 깨지면
    CD 임포트가 무의미해진다). 상한 초과 시 413 — 이미 기록된 파일은 남으므로
    호출자가 임시 디렉터리를 정리해야 한다.
    """
    total = 0
    entries = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        entries += 1
        if entries > max_entries:
            raise HTTPException(
                413, f"압축 파일의 항목 수가 너무 많습니다(최대 {max_entries}개)"
            )
        rel = _sanitize_zip_name(info.filename)
        if rel is None:
            logger.warning("ZIP 멤버 경로를 건너뜀(정규화 결과 비어 있음): %r",
                           info.filename)
            continue
        # 헤더 선판정 — 한 바이트도 읽지 않고 거른다(위 주석: 이 경로에선 유효한 상한).
        if info.file_size > max_member_bytes:
            raise _too_large(f"멤버 {info.filename}", max_member_bytes)
        if total + info.file_size > max_total_bytes:
            raise _too_large("누적", max_total_bytes)

        dest_path = os.path.join(dest_dir, rel)
        parent = os.path.dirname(dest_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        total += _stream_member_to_disk(
            zf, info, dest_path,
            max_member_bytes=max_member_bytes,
            max_remaining_bytes=max_total_bytes - total,
        )
    return total


def bounded_zip_read(
    zf: zipfile.ZipFile,
    name: str | zipfile.ZipInfo,
    max_bytes: int,
) -> bytes:
    """`ZipFile.read`의 상한 있는 대체 — 멤버를 RAM에 올려야 할 때만 쓴다.

    상한을 넘으면 413. 디스크로 흘릴 수 있는 경우엔 `bounded_zip_extractall`
    (또는 `_stream_member_to_disk`)을 쓰는 편이 항상 낫다.
    """
    info = zf.getinfo(name) if isinstance(name, str) else name
    if info.file_size > max_bytes:
        raise _too_large(f"멤버 {info.filename}", max_bytes)
    buf = bytearray()
    with zf.open(info) as src:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            buf += chunk
            if len(buf) > max_bytes:
                raise _too_large(f"멤버 {info.filename}", max_bytes)
    return bytes(buf)
