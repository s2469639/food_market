"""Offline, fixed-country comparison using reviewed public evidence, not an agent."""

from copy import deepcopy
import json
from pathlib import Path

from .analysis import analyze
from .comtrade import ComtradeClient


FIXTURE = Path(__file__).parent / "fixtures" / "first_comparison.json"


def build_comparison():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for envelope in fixture["envelopes"]:
        ComtradeClient._validate(envelope["response"])
    annual, summaries = analyze(fixture["envelopes"], [36, 392], [2022, 2023, 2024])
    countries = deepcopy(fixture["countries"])
    for country in countries:
        code = country["reporter_code"]
        country["annual"] = [row for row in annual if row["reporter_code"] == code]
        country["quantitative"] = next(row for row in summaries if row["reporter_code"] == code)
    return dict(mode="fixed_country_trial", product=fixture["product"],
                period=[2022, 2024], hs_code="190531", classification="H6",
                countries=countries, evidence=fixture["evidence"],
                provenance=fixture["provenance"],
                limitations=["공개자료를 보관한 고정 2개국 연결 시험입니다. 자동 발굴·AI 분석·TOP 3 추천 결과가 아닙니다.",
                             "소비 근거와 연결 가설은 사전 작성했습니다. 외부 API를 호출하지 않습니다.",
                             "일본의 품목 범위 차이로 두 나라의 비스킷 전체 시장 우열은 비교하지 않습니다."])
