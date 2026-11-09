"""Deterministic indicators. Missing data stays missing; no opportunity ranking."""

import math
import pandas as pd

from .comtrade import DataError


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise DataError("통계값에 논리값이 포함됐습니다.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise DataError("통계값이 숫자가 아닙니다.") from None
    if not math.isfinite(result) or result < 0:
        raise DataError("통계값이 음수이거나 유한한 수가 아닙니다.")
    return result


def analyze(envelopes, reporters, years):
    years = sorted(set(years))
    reporters = sorted(set(reporters))
    if len(years) < 2 or years != list(range(years[0], years[-1] + 1)):
        raise DataError("성장 분석에는 연속된 최소 2개 연도가 필요합니다.")
    rows, seen = [], set()
    for envelope in envelopes:
        for row in envelope["response"]["data"]:
            code, year = row.get("reporterCode"), row.get("refYear")
            valid = (code in reporters and year in years and row.get("period") == str(year)
                     and row.get("cmdCode") == "190531" and row.get("classificationCode") == "H6"
                     and row.get("flowCode") == "M" and row.get("partnerCode") == 0
                     and row.get("partner2Code") == 0 and row.get("customsCode") == "C00"
                     and row.get("motCode") == 0 and row.get("typeCode") == "C"
                     and row.get("freqCode") == "A" and row.get("aggrLevel") == 6)
            if not valid:
                raise DataError("선택한 국가·연도·HS 버전 또는 집계 조건과 응답이 다릅니다.")
            key = code, year
            if key in seen:
                raise DataError("국가·연도 중복 행이 있습니다. 합산하지 않고 분석을 중단합니다.")
            seen.add(key)
            rows.append(dict(reporter_code=code, year=year, country=row.get("reporterDesc"),
                             import_usd=_number(row.get("primaryValue")),
                             net_weight_kg=_number(row.get("netWgt")),
                             is_reported=row.get("isReported"), is_aggregate=row.get("isAggregate"),
                             weight_estimated=row.get("isNetWgtEstimated"),
                             source_url=envelope["source_url"], retrieved_at=envelope["retrieved_at"]))
    columns = ["reporter_code", "year", "country", "import_usd", "net_weight_kg", "is_reported",
               "is_aggregate", "weight_estimated", "source_url", "retrieved_at"]
    frame = pd.DataFrame(rows, columns=columns).set_index(["reporter_code", "year"])
    grid = pd.MultiIndex.from_product([reporters, years], names=["reporter_code", "year"])
    frame = frame.reindex(grid).reset_index()
    frame["missing_import"] = frame["import_usd"].isna()
    previous = frame.groupby("reporter_code")["import_usd"].shift(1)
    frame["change_usd"] = frame["import_usd"] - previous
    frame["yoy_pct"] = (frame["import_usd"] / previous.where(previous > 0) - 1) * 100
    summaries = []
    for code, group in frame.groupby("reporter_code", sort=True):
        values = group["import_usd"]
        complete = bool(values.notna().all())
        first, last = values.iloc[0], values.iloc[-1]
        cagr = ((last / first) ** (1 / (years[-1] - years[0])) - 1) * 100 if complete and first > 0 else None
        names = group["country"].dropna()
        summaries.append(dict(reporter_code=int(code), country=names.iloc[-1] if len(names) else None,
                              start_year=years[0], end_year=years[-1], complete=complete,
                              missing_years=group.loc[group.missing_import, "year"].tolist(),
                              change_usd=float(last - first) if complete else None, cagr_pct=cagr,
                              requires_review=True))
    # JSON conversion maps pandas missing values to null, never NaN or invented zeroes.
    import json
    return json.loads(frame.to_json(orient="records", force_ascii=False)), summaries
