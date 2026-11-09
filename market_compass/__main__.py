import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from .analysis import analyze
from .comtrade import ComtradeClient, DataError, write_json


def main():
    parser = argparse.ArgumentParser(description="Market Compass: HS190531 공개 수입통계 검증")
    parser.add_argument("--reporters", nargs="+", type=int, default=[36, 392, 842])
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--refresh", action="store_true", help="저장된 응답 대신 API 재조회")
    parser.add_argument("--cache-dir", default="data/raw")
    parser.add_argument("--output", default="reports/quantitative.json")
    args = parser.parse_args()
    if args.end_year < args.start_year or args.end_year - args.start_year > 9:
        parser.error("분석 기간은 순서대로 최대 10개 연도를 지정하세요.")
    if Path(args.output).suffix.lower() != ".json":
        parser.error("출력은 .json 파일로 지정하세요.")
    try:
        years = list(range(args.start_year, args.end_year + 1))
        client = ComtradeClient(args.cache_dir)
        envelopes = [client.fetch_year(year, args.reporters, refresh=args.refresh) for year in years]
        observed_rows = sum(len(item["response"]["data"]) for item in envelopes)
        if observed_rows == 0:
            raise DataError("선택 조건의 데이터가 0건입니다. 보고서를 생성하지 않습니다.")
        annual, summary = analyze(envelopes, args.reporters, years)
        result = dict(generated_at=datetime.now(timezone.utc).isoformat(), hs_code="190531",
                      status="complete" if all(item["complete"] for item in summary) else "incomplete",
                      observed_rows=observed_rows,
                      classification="H6 (HS 2022)", annual=annual, summary=summary,
                      limitations=["공개 preview API 응답이며 국가 통계와 대조 검증이 필요합니다.",
                                   "선택 국가의 정량 탐색 결과이며 수출 기회 순위가 아닙니다.",
                                   "수입액은 명목 USD이며 기업 매출·실제 소비량을 의미하지 않습니다.",
                                   "집계·보고·중량 추정 상태와 출처는 연도별 행에서 확인하세요.",
                                   "결측은 0이 아닙니다. 기준값 0의 성장률은 계산하지 않습니다.",
                                   "소비근거·제품별 HS 적용·규제·진입 부담은 아직 검증되지 않았습니다."])
        write_json(args.output, result)
        print(f"정량 보고서 저장 완료: {args.output} (국가 {len(summary)}개, 기간 {years[0]}–{years[-1]})")
        print(f"실제 응답 {observed_rows}건 / 요청 국가·연도 {len(summary) * len(years)}건")
        print("검증 전 수치입니다. 수출 기회 추천 또는 TOP 3로 해석하지 마세요.")
        return 0
    except DataError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
