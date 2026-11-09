"""Small, sequential requests to the official public preview API; no credentials."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
MAX_RECORDS = 500


class DataError(Exception):
    """Safe, user-facing failure: never include headers or credentials."""


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ComtradeClient:
    def __init__(self, cache_dir="data/raw", *, opener=urlopen, sleep=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.opener = opener
        self.sleep = sleep
        self._requested = False

    def fetch_year(self, year, reporters, *, refresh=False):
        reporters = sorted(set(reporters))
        if not 2022 <= year <= datetime.now(timezone.utc).year - 1:
            raise DataError("H6 조회 연도는 2022년부터 직전 연도까지 지정하세요.")
        if not reporters or len(reporters) > 5 or any(type(c) is not int or c <= 0 for c in reporters):
            raise DataError("국가 코드는 양의 정수로 1~5개 지정하세요.")
        query = dict(period=str(year), reporterCode=",".join(map(str, reporters)),
                     cmdCode="190531", flowCode="M", partnerCode="0", partner2Code="0",
                     customsCode="C00", motCode="0", maxRecords=MAX_RECORDS,
                     breakdownMode="classic", includeDesc="true")
        url = BASE_URL + "?" + urlencode(query)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists() and not refresh:
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if envelope.get("source_url") != url or not envelope.get("retrieved_at"):
                    raise ValueError()
                self._validate(envelope["response"])
                return envelope
            except (ValueError, KeyError, TypeError, DataError):
                raise DataError("캐시가 유효하지 않습니다. --refresh로 다시 조회하세요.") from None
        if self._requested:
            self.sleep(2)
        self._requested = True
        for attempt in range(3):
            try:
                with self.opener(url, timeout=30) as response:
                    payload = json.load(response)
                self._validate(payload)
                envelope = {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "query": query, "response": payload}
                write_json(path, envelope)
                return envelope
            except HTTPError as error:
                code = error.code
                retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                if code in (429, 500, 502, 503, 504) and attempt < 2:
                    # Do not ignore a server-requested long wait or retry forever.
                    if retry_after and (not retry_after.isdigit() or int(retry_after) > 30):
                        raise DataError("API가 대기를 요청했습니다. 나중에 다시 실행하세요.") from None
                    self.sleep(max(5 * (attempt + 1), int(retry_after or 0)))
                    continue
                raise DataError(f"Comtrade HTTP {code}: 접근 정책 또는 API 제한을 확인하세요.") from None
            except URLError:
                if attempt < 2:
                    self.sleep(5 * (attempt + 1))
                    continue
                raise DataError("Comtrade 연결 실패: 네트워크·프록시 설정을 확인하세요.") from None
            except (TimeoutError, OSError, ValueError):
                raise DataError("응답 해석 또는 로컬 저장 실패. 부분 결과를 분석에 사용하지 않습니다.") from None

    @staticmethod
    def _validate(payload):
        if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("data"), list):
            raise DataError("Comtrade 응답 형식 또는 API 오류를 확인하세요.")
        rows = payload["data"]
        if payload.get("count") != len(rows) or len(rows) >= MAX_RECORDS:
            raise DataError("응답 건수가 불일치하거나 잘렸을 가능성이 있습니다.")
        if any(not isinstance(row, dict) for row in rows):
            raise DataError("Comtrade 행 형식이 올바르지 않습니다.")
