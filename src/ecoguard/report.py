"""Build a human-review evidence packet as JSON and self-contained HTML."""

from __future__ import annotations

import html
from typing import Any


def build_evidence_packet(
    normalized: dict[str, Any],
    legal_evaluation: dict[str, Any],
    legal_issue_citations: dict[str, Any],
    cbam: dict[str, Any],
    forest: dict[str, Any],
) -> dict[str, Any]:
    issue_count = len(normalized["issues"])
    if issue_count:
        decision_reason = (
            f"정규화 과정에서 {issue_count}개 검토 이슈가 확인되어 "
            "자동 판단하지 않습니다."
        )
    else:
        decision_reason = "교육용 PoC는 자동 승인하지 않으며 사람이 최종 검토합니다."
    return {
        "project": "EcoGuard",
        "case_id": normalized["case_id"],
        "classification": "synthetic educational proof-of-concept",
        "decision": {
            "status": "human_review_required",
            "reason": decision_reason,
        },
        "pipeline": [
            "OCR-like raw records",
            "normalization and provenance",
            "cross-document checks",
            "case-issue to article citation retrieval",
            "CBAM exposure scenarios",
            "independent synthetic NDVI baseline",
            "human review packet",
        ],
        "normalized_evidence": normalized,
        "legal_retrieval_evaluation": legal_evaluation,
        "legal_issue_citations": legal_issue_citations,
        "cbam_exposure": cbam,
        "forest_change_baseline": forest,
        "boundaries": [
            "모든 사례 입력과 계산 시나리오는 합성 데이터입니다.",
            "OCR 엔진이 아니라 OCR 이후의 전처리와 증거 연결을 재현합니다.",
            "법률 검색 결과와 계산은 법률·통관·금융 자문이 아닙니다.",
            "산림 변화 모듈은 거래 사례와 분리된 합성 픽셀 기반 공개 베이스라인입니다.",
            "EcoGuard는 하나은행의 공식 제품이 아닙니다.",
        ],
    }


def _fmt_money(value: str) -> str:
    return "€" + format(float(value), ",.2f")


def render_html(packet: dict[str, Any], forest_svg: str) -> str:
    normalized = packet["normalized_evidence"]
    cbam = packet["cbam_exposure"]
    legal = packet["legal_retrieval_evaluation"]
    legal_issues = packet["legal_issue_citations"]
    forest = packet["forest_change_baseline"]

    field_rows: list[str] = []
    for field, details in normalized["fields"].items():
        source = details["selected_from"]
        value = "missing" if details["value"] is None else details["value"]
        unit = details["unit"] or ""
        field_rows.append(
            "<tr>"
            f"<td><code>{html.escape(field)}</code></td>"
            f"<td>{html.escape(str(value))} {html.escape(unit)}</td>"
            f"<td>{html.escape(source['document'])}<br>"
            f"<small>{html.escape(source['location'])}</small></td>"
            f"<td>{source['confidence']:.2f}</td>"
            "</tr>"
        )

    issue_rows = "".join(
        "<li>"
        f"<span class='pill {html.escape(issue['severity'])}'>"
        f"{html.escape(issue['severity'].upper())}</span>"
        f"<strong>{html.escape(issue['code'])}</strong> — "
        f"{html.escape(issue['message'])}"
        "</li>"
        for issue in normalized["issues"]
    )

    legal_rows: list[str] = []
    for item in legal_issues["items"]:
        first = item["results"][0] if item["results"] else None
        if first is None:
            citation = "<strong>ABSTAIN</strong><br><small>근거 점수가 임계값에 미달했습니다.</small>"
            source = "—"
        else:
            citation = (
                f"<strong>{html.escape(first['regulation'])} "
                f"{html.escape(first['article'])}</strong><br>"
                f"<small>{html.escape(first['summary_ko'])}</small>"
            )
            source = (
                f"<a href='{html.escape(first['url'])}'>official source</a>"
            )
        legal_rows.append(
            "<tr>"
            f"<td><strong>{html.escape(item['issue']['field'] or item['issue']['code'])}</strong><br>"
            f"<small>{html.escape(item['query'])}</small></td>"
            f"<td>{citation}</td>"
            f"<td>{source}</td>"
            "</tr>"
        )

    pipeline = " <span aria-hidden='true'>→</span> ".join(
        html.escape(step) for step in packet["pipeline"]
    )
    boundaries = "".join(
        f"<li>{html.escape(item)}</li>" for item in packet["boundaries"]
    )
    line_item_summary = " + ".join(
        f"{html.escape(item['item'])} "
        f"{html.escape(item['embedded_emissions_tco2e'])}"
        for item in cbam["actual_data_scenario"]["line_items"]
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EcoGuard evidence report — {html.escape(packet["case_id"])}</title>
  <style>
    :root {{ --ink:#123c35; --muted:#60756f; --line:#d8e6e1; --mint:#04a887;
      --soft:#f2f7f4; --warn:#f6a723; --high:#f05a47; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:#edf4f1;
      font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1120px,calc(100% - 32px)); margin:32px auto; }}
    .hero,.panel {{ background:white; border:1px solid var(--line); border-radius:22px;
      padding:clamp(22px,4vw,44px); box-shadow:0 12px 34px rgba(18,60,53,.06); }}
    .hero {{ background:linear-gradient(135deg,#0e3c34,#14594d); color:white; }}
    .eyebrow {{ letter-spacing:.12em; text-transform:uppercase; font-size:12px; opacity:.74; }}
    h1 {{ margin:.2em 0 0; font-size:clamp(38px,7vw,72px); line-height:1; }}
    h2 {{ margin:0 0 14px; font-size:clamp(24px,4vw,36px); }}
    h3 {{ margin:0 0 8px; }}
    .lede {{ max-width:780px; font-size:18px; }}
    .notice {{ display:inline-block; margin-top:18px; padding:7px 12px; border-radius:999px;
      background:rgba(255,255,255,.12); }}
    .panel {{ margin-top:20px; }}
    .flow {{ padding:18px; border-radius:14px; background:var(--soft); font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
    .metric {{ padding:18px; border:1px solid var(--line); border-radius:16px; }}
    .metric b {{ display:block; font-size:26px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ padding:12px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
    code {{ font-size:12px; }}
    small,.muted {{ color:var(--muted); }}
    ul.clean {{ padding:0; list-style:none; }}
    ul.clean li {{ margin:10px 0; }}
    .pill {{ display:inline-block; min-width:64px; margin-right:8px; padding:2px 8px;
      border-radius:999px; color:white; font-size:11px; text-align:center; }}
    .pill.review {{ background:var(--warn); }}
    .pill.high {{ background:var(--high); }}
    a {{ color:#087e68; }}
    .forest svg {{ width:100%; height:auto; }}
    footer {{ margin:20px 0 48px; color:var(--muted); text-align:center; }}
    @media (max-width:760px) {{
      .grid {{ grid-template-columns:1fr; }}
      .table-wrap {{ overflow-x:auto; }}
      th,td {{ min-width:150px; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="eyebrow">Synthetic evidence packet · human in the loop</div>
    <h1>EcoGuard</h1>
    <p class="lede">비정형 원자료에서 계산 결과만 꺼내지 않고, 어떤 값이 어느 문서에서
    왔으며 어떤 근거와 검토 항목으로 이어졌는지 한 묶음으로 남긴 재현 보고서입니다.</p>
    <span class="notice">Case {html.escape(packet["case_id"])} · 자동 승인 아님</span>
  </section>

  <section class="panel">
    <h2>Evidence flow</h2>
    <p class="flow">{pipeline}</p>
    <p>판단 상태: <strong>HUMAN REVIEW REQUIRED</strong> —
    {html.escape(packet["decision"]["reason"])}</p>
  </section>

  <section class="panel">
    <h2>1. Normalized data with provenance</h2>
    <p class="muted">같은 개념의 kg·MT·메모 표현을 정규화하되 원문 위치와 후보값을 보존합니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Field</th><th>Selected value</th><th>Source</th><th>Confidence</th></tr></thead>
      <tbody>{"".join(field_rows)}</tbody>
    </table></div>
    <h3>Review queue</h3>
    <ul class="clean">{issue_rows}</ul>
  </section>

  <section class="panel">
    <h2>2. Article-level legal retrieval</h2>
    <div class="grid">
      <div class="metric"><span>Evaluation cases</span><b>{legal["case_count"]}</b></div>
      <div class="metric"><span>Hit rate @ {legal["k"]}</span><b>{legal["hit_rate_at_k"]:.0%}</b></div>
      <div class="metric"><span>MRR</span><b>{legal["mean_reciprocal_rank"]:.2f}</b></div>
    </div>
    <p class="muted">작은 공개 코퍼스에서 기대 조문 citation을 회수하는지 보는 기술 베이스라인입니다.
    생성형 법률 답변이나 법률 자문 정확도를 뜻하지 않습니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Detected issue and query</th><th>Top citation</th><th>Source</th></tr></thead>
      <tbody>{"".join(legal_rows)}</tbody>
    </table></div>
  </section>

  <section class="panel">
    <h2>3. CBAM exposure scenarios</h2>
    <div class="grid">
      <div class="metric"><span>Actual-data scenario</span>
        <b>{_fmt_money(cbam["actual_data_scenario"]["exposure_eur"])}</b>
        <small>{cbam["actual_data_scenario"]["embedded_emissions_tco2e"]} tCO2e</small></div>
      <div class="metric"><span>Default-value scenario</span>
        <b>{_fmt_money(cbam["default_value_scenario"]["exposure_eur"])}</b>
        <small>{cbam["default_value_scenario"]["embedded_emissions_tco2e"]} tCO2e</small></div>
      <div class="metric"><span>Scenario difference</span>
        <b>{_fmt_money(cbam["difference"]["exposure_eur"])}</b>
        <small>입력 가정에 따른 비교값</small></div>
    </div>
    <p><code>{html.escape(cbam["method"])}</code></p>
    <p><strong>{line_item_summary}</strong> =
    <strong>{cbam["actual_data_scenario"]["embedded_emissions_tco2e"]} tCO2e</strong> · 품목 중량 합계와 출하량 일치:
    <strong>{str(cbam["reconciliation"]["mass_matches"]).upper()}</strong> ·
    가중 집약도 허용오차 일치:
    <strong>{str(cbam["reconciliation"]["intensity_matches"]).upper()}</strong></p>
    <p class="muted">가격, 집약도, 적용계수는 결과와 함께 기록됩니다. 이 값은 공식 신고액이 아닙니다.</p>
  </section>

  <section class="panel forest">
    <h2>4. Independent synthetic forest baseline</h2>
    <p>손실 플래그 <strong>{forest["summary"]["loss_pixel_count"]} /
    {forest["grid"]["pixel_count"]}</strong> · 평균 NDVI 변화
    <strong>{forest["summary"]["mean_ndvi_change"]:+.4f}</strong> ·
    연속 영역 <strong>{forest["summary"]["contiguous_region_count"]}</strong> ·
    합성 면적 <strong>{forest["summary"]["loss_area_m2"]:,.0f} m²</strong></p>
    <p class="muted">이 산림 fixture는 {html.escape(packet["case_id"])} 거래와 결합된
    증빙이 아니라, 별도의 합성 기술 기준선 {html.escape(forest["case_id"])}입니다.</p>
    {forest_svg}
  </section>

  <section class="panel">
    <h2>Boundaries</h2>
    <ul>{boundaries}</ul>
  </section>
  <footer>EcoGuard · Team UniHana · 2026 · public reproducibility baseline</footer>
</main>
</body>
</html>
"""
