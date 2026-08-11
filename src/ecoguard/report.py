"""Build a human-review evidence packet as JSON and self-contained HTML."""

from __future__ import annotations

import html
from decimal import Decimal
from typing import Any


def build_evidence_packet(
    extraction: dict[str, Any],
    normalized: dict[str, Any],
    legal_evaluation: dict[str, Any],
    legal_issue_citations: dict[str, Any],
    cbam: dict[str, Any],
    forest: dict[str, Any],
) -> dict[str, Any]:
    high_count = normalized["summary"].get("high_issue_count", 0)
    review_count = normalized["summary"].get("review_issue_count", 0)
    issue_count = len(normalized["issues"])
    if issue_count:
        decision_reason = (
            f"전처리 검증에서 high {high_count}건, review {review_count}건이 "
            "확인되어 자동 판단하지 않습니다."
        )
    else:
        decision_reason = "교육용 PoC는 자동 승인하지 않으며 사람이 최종 검토합니다."
    return {
        "schema_version": "evidence-packet/2.0",
        "project": "EcoGuard",
        "case_id": normalized["case_id"],
        "classification": "synthetic educational proof-of-concept",
        "decision": {
            "status": "human_review_required",
            "reason": decision_reason,
        },
        "proof_summary": {
            "source_document_count": extraction["summary"]["document_count"],
            "source_line_count": extraction["summary"]["line_count"],
            "extracted_candidate_count": extraction["summary"]["matched_line_count"],
            "normalized_field_count": normalized["summary"]["field_count"],
            "review_issue_count": issue_count,
            "cbam_trace_step_count": len(
                cbam["technical_inventory"]["calculation_trace"]
            ),
            "legal_evaluation_case_count": legal_evaluation["case_count"],
            "forest_reference_pixel_count": forest["grid"]["pixel_count"],
        },
        "pipeline": [
            "document-oriented synthetic OCR payload",
            "alias extraction with source spans and SHA-256",
            "unit normalization and authority-aware candidate selection",
            "cross-document validation ledger",
            "field-weighted legal citation retrieval and abstention evaluation",
            "component-level CBAM technical inventory and price sensitivity",
            "independent synthetic NDVI reference-mask evaluation",
            "human review packet",
        ],
        "extraction": extraction,
        "normalized_evidence": normalized,
        "legal_retrieval_evaluation": legal_evaluation,
        "legal_issue_citations": legal_issue_citations,
        "cbam_exposure": cbam,
        "forest_change_baseline": forest,
        "boundaries": [
            "모든 사례 입력과 계산 시나리오는 합성 데이터입니다.",
            "OCR 이미지 인식 모델이 아니라 OCR 이후의 추출·정규화·증거 연결을 재현합니다.",
            "법률 모듈은 작은 조문 메타데이터의 retrieval 기준선이며 LLM 답변이나 법률 자문이 아닙니다.",
            "CBAM 결과는 직접·간접·전구물질을 포함한 기술 인벤토리 기반 가격 민감도이며 법정 의무액이 아닙니다.",
            "산림 지표는 합성 reference mask에 대한 평가 코드 검증값이며 실제 위성 모델 정확도가 아닙니다.",
            "사람이 증빙과 규제 범위를 확인하며 EcoGuard는 자동 승인·거절하지 않습니다.",
            "EcoGuard는 하나은행의 공식 제품이 아닙니다.",
        ],
    }


def _fmt_money(value: str) -> str:
    return "€" + format(Decimal(value), ",.2f")


def _fmt_metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _short_hash(value: str | None) -> str:
    return "—" if not value else value[:12] + "…"


def _escape(value: Any) -> str:
    return html.escape(str(value))


def render_html(packet: dict[str, Any], forest_svg: str) -> str:
    extraction = packet["extraction"]
    normalized = packet["normalized_evidence"]
    cbam = packet["cbam_exposure"]
    legal = packet["legal_retrieval_evaluation"]
    legal_issues = packet["legal_issue_citations"]
    forest = packet["forest_change_baseline"]

    document_rows = "".join(
        "<tr>"
        f"<td><code>{_escape(document['document_id'])}</code></td>"
        f"<td>{_escape(document['document_type'])}</td>"
        f"<td>{document['matched_line_count']} / {document['line_count']}</td>"
        f"<td><code>{_short_hash(document['sha256'])}</code></td>"
        "</tr>"
        for document in extraction["documents"]
    )

    field_rows: list[str] = []
    for field, details in sorted(normalized["fields"].items()):
        source = details["selected_from"]
        value = "missing" if details["value"] is None else details["value"]
        unit = details["unit"] or ""
        field_rows.append(
            "<tr>"
            f"<td><code>{_escape(field)}</code></td>"
            f"<td><strong>{_escape(value)} {_escape(unit)}</strong><br>"
            f"<small>{_escape(details['transformation'])}</small></td>"
            f"<td>{_escape(source['document'])}<br>"
            f"<small>{_escape(source['location'])} · authority "
            f"{source['authority_rank']} · conf {source['confidence']:.2f}</small></td>"
            f"<td>{len(details['candidates'])}<br>"
            f"<small><code>{_short_hash(source.get('line_sha256'))}</code></small></td>"
            "</tr>"
        )

    issue_rows = (
        "".join(
            "<li>"
            f"<span class='pill {_escape(issue['severity'])}'>"
            f"{_escape(issue['severity'].upper())}</span>"
            f"<strong>{_escape(issue['code'])}</strong>"
            f"{(' · <code>' + _escape(issue.get('field')) + '</code>') if issue.get('field') else ''}"
            f" — {_escape(issue['message'])}"
            "</li>"
            for issue in normalized["issues"]
        )
        or "<li>No review issue.</li>"
    )
    observation_rows = (
        "".join(
            "<li><span class='pill info'>INFO</span>"
            f"<strong>{_escape(item['code'])}</strong> · "
            f"<code>{_escape(item['field'])}</code> — {_escape(item['message'])}</li>"
            for item in normalized.get("observations", [])
        )
        or "<li>No within-tolerance observation.</li>"
    )

    legal_rows: list[str] = []
    for item in legal_issues["items"]:
        first = item["results"][0] if item["results"] else None
        if first is None:
            citation = (
                "<strong>ABSTAIN</strong><br>"
                f"<small>{_escape(item.get('reason_code', 'no_supported_citation'))}</small>"
            )
            source = "—"
        else:
            citation_data = first.get("citation", first)
            trace = first.get("score_trace", {})
            citation = (
                f"<strong>{_escape(citation_data['regulation'])} "
                f"{_escape(citation_data['article'])} § {_escape(citation_data.get('paragraph'))}</strong><br>"
                f"<small>{_escape(first['summary_ko'])}<br>score "
                f"{first['score']:.3f} · BM25 "
                f"{trace.get('bm25_word', 0):.3f} + phrase "
                f"{trace.get('concept_phrase_bonus', 0):.3f}</small>"
            )
            source = (
                f"<a href='{_escape(citation_data['url'])}'>EUR-Lex</a><br>"
                f"<small><code>{_short_hash(citation_data.get('corpus_entry_sha256'))}</code></small>"
            )
        legal_rows.append(
            "<tr>"
            f"<td><strong>{_escape(item['issue'].get('field') or item['issue']['code'])}</strong><br>"
            f"<small>{_escape(item['query'])}</small></td>"
            f"<td>{citation}</td>"
            f"<td>{source}</td>"
            "</tr>"
        )

    component_rows: list[str] = []
    for item in cbam["technical_inventory"]["items"]:
        for component in item["components"]:
            component_rows.append(
                "<tr>"
                f"<td><strong>{_escape(item['item_id'])}</strong><br>"
                f"<small>{_escape(item['installation_id'])}</small></td>"
                f"<td>{_escape(component['label'])}</td>"
                f"<td>{_escape(item['mass_t'])} t × "
                f"{_escape(component['intensity_tco2e_per_t'])} tCO₂e/t</td>"
                f"<td><strong>{_escape(component['embedded_emissions_tco2e'])} tCO₂e</strong><br>"
                f"<small><code>{_escape(component['calculation_step_id'])}</code></small></td>"
                "</tr>"
            )

    sensitivity_rows = "".join(
        "<tr>"
        f"<td><code>{_escape(scenario['scenario_id'])}</code><br>"
        f"<small>{_escape(scenario['classification'])}</small></td>"
        f"<td>{_escape(scenario['inputs']['scenario_exposure_factor'])}</td>"
        f"<td>{_fmt_money(scenario['inputs']['certificate_price_eur_per_tco2e'])}</td>"
        f"<td>{_fmt_money(scenario['inputs']['third_country_price_eur_per_tco2e'])}</td>"
        f"<td><strong>{_fmt_money(scenario['exposure_eur'])}</strong></td>"
        "</tr>"
        for scenario in cbam["sensitivity_scenarios"]
    )

    input_rows = "".join(
        "<tr>"
        f"<td><code>{_escape(name)}</code></td>"
        f"<td>{details['bytes']:,}</td>"
        f"<td><code>{_escape(details['sha256'])}</code></td>"
        "</tr>"
        for name, details in sorted(
            packet.get("reproduction", {}).get("inputs", {}).items()
        )
    )
    pipeline = " <span aria-hidden='true'>→</span> ".join(
        _escape(step) for step in packet["pipeline"]
    )
    boundaries = "".join(f"<li>{_escape(item)}</li>" for item in packet["boundaries"])
    forest_metrics = forest["evaluation"]["metrics"]
    confusion = forest["evaluation"]["confusion_matrix"]
    axes = cbam["technical_inventory"]["component_axes"]

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EcoGuard evidence report — {_escape(packet["case_id"])}</title>
  <style>
    :root {{ --ink:#123c35; --muted:#526c65; --line:#d8e6e1; --mint:#04a887;
      --soft:#f2f7f4; --warn:#b86f00; --high:#d34132; --info:#3478a3; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:#edf4f1;
      font:15px/1.62 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:32px auto; }}
    .hero,.panel {{ background:white; border:1px solid var(--line); border-radius:22px;
      padding:clamp(22px,4vw,44px); box-shadow:0 12px 34px rgba(18,60,53,.06); }}
    .hero {{ background:linear-gradient(135deg,#0e3c34,#14594d); color:white; }}
    .eyebrow {{ letter-spacing:.12em; text-transform:uppercase; font-size:12px; opacity:.78; }}
    h1 {{ margin:.2em 0 0; font-size:clamp(38px,7vw,72px); line-height:1; }}
    h2 {{ margin:0 0 14px; font-size:clamp(24px,4vw,36px); }}
    h3 {{ margin:24px 0 8px; }}
    .lede {{ max-width:850px; font-size:18px; }}
    .notice {{ display:inline-block; margin-top:18px; padding:7px 12px; border-radius:999px;
      background:rgba(255,255,255,.12); }}
    .panel {{ margin-top:20px; }}
    .flow {{ padding:18px; border-radius:14px; background:var(--soft); font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }}
    .metric {{ padding:18px; border:1px solid var(--line); border-radius:16px; }}
    .metric b {{ display:block; font-size:26px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ padding:12px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
    code {{ font-size:12px; overflow-wrap:anywhere; }}
    small,.muted {{ color:var(--muted); }}
    ul.clean {{ padding:0; list-style:none; }}
    ul.clean li {{ margin:10px 0; }}
    .pill {{ display:inline-block; min-width:64px; margin-right:8px; padding:2px 8px;
      border-radius:999px; color:white; font-size:11px; text-align:center; }}
    .pill.review {{ background:var(--warn); }} .pill.high {{ background:var(--high); }}
    .pill.info {{ background:var(--info); }} a {{ color:#087e68; }}
    .forest svg {{ width:100%; height:auto; }}
    footer {{ margin:20px 0 48px; color:var(--muted); text-align:center; }}
    @media (max-width:900px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} }}
    @media (max-width:620px) {{ .grid {{ grid-template-columns:1fr; }}
      .table-wrap {{ overflow-x:auto; }} th,td {{ min-width:150px; }} }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="eyebrow">Synthetic evidence packet · deterministic reproduction</div>
    <h1>EcoGuard</h1>
    <p class="lede">숫자만 맞히는 데모가 아니라, 7개 문서의 원문 line에서 어떤 후보를
    선택했고 어떤 검증과 조문 검색, 산식 trace를 거쳐 결과에 도달했는지 재실행하는 증거 패킷입니다.</p>
    <span class="notice">Case {_escape(packet["case_id"])} · HUMAN REVIEW REQUIRED</span>
  </section>

  <section class="panel">
    <h2>Evidence flow</h2>
    <p class="flow">{pipeline}</p>
    <div class="grid">
      <div class="metric"><span>Documents</span><b>{extraction['summary']['document_count']}</b></div>
      <div class="metric"><span>OCR lines</span><b>{extraction['summary']['line_count']}</b></div>
      <div class="metric"><span>Field candidates</span><b>{extraction['summary']['matched_line_count']}</b></div>
      <div class="metric"><span>Review issues</span><b>{len(normalized['issues'])}</b></div>
    </div>
    <p>판단 상태: <strong>HUMAN REVIEW REQUIRED</strong> — {_escape(packet['decision']['reason'])}</p>
  </section>

  <section class="panel">
    <h2>1. Document ingestion and lineage</h2>
    <p class="muted">입력은 OCR 이미지가 아니라 OCR 직후 line payload입니다. 모든 후보에는 원문 위치,
    문자 span, line/document SHA-256이 남습니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Document</th><th>Type</th><th>Matched / lines</th><th>SHA-256</th></tr></thead>
      <tbody>{document_rows}</tbody>
    </table></div>
  </section>

  <section class="panel">
    <h2>2. Normalization, selection and review ledger</h2>
    <p class="muted">parse 가능 여부 → 문서 권위 → confidence → 안정적인 입력 순서로 후보를 선택합니다.
    선택되지 않은 값과 parse 실패도 삭제하지 않습니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Field</th><th>Selected value</th><th>Evidence</th><th>Candidates / hash</th></tr></thead>
      <tbody>{''.join(field_rows)}</tbody>
    </table></div>
    <h3>Review queue</h3><ul class="clean">{issue_rows}</ul>
    <h3>Within-tolerance observations</h3><ul class="clean">{observation_rows}</ul>
  </section>

  <section class="panel">
    <h2>3. Legal citation retrieval baseline</h2>
    <div class="grid">
      <div class="metric"><span>Positive / distractor</span><b>{legal['positive_case_count']} / {legal['distractor_case_count']}</b></div>
      <div class="metric"><span>Recall @ {legal['k']}</span><b>{legal['recall_at_k']:.0%}</b></div>
      <div class="metric"><span>Negative abstention</span><b>{legal['negative_abstention_rate']:.0%}</b></div>
      <div class="metric"><span>Trace coverage</span><b>{legal['trace_coverage']:.0%}</b></div>
    </div>
    <p class="muted">field-weighted BM25F, 명시적 instrument/intent gate와 기권 정책을 평가합니다.
    Recall과 MRR의 분모는 positive+distractor {legal['retrieval_case_count']}건입니다.
    MRR {legal['mean_reciprocal_rank']:.3f}, false support {legal['false_support_rate']:.1%},
    instrument leakage {legal['instrument_leakage_at_k']:.1%}. 고정 합성 회귀셋 성능이며 일반 법률 정확도가 아닙니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Detected issue and query</th><th>Top citation and score trace</th><th>Source</th></tr></thead>
      <tbody>{''.join(legal_rows)}</tbody>
    </table></div>
    <p class="muted">매핑되지 않은 데이터 품질 이슈: {legal_issues['unmapped_issue_count']}건.
    조용히 버리지 않고 JSON의 <code>unmapped_issues</code>에 보존합니다.</p>
  </section>

  <section class="panel">
    <h2>4. CBAM component trace and price sensitivity</h2>
    <div class="grid">
      <div class="metric"><span>Direct axis</span><b>{axes['direct_tco2e']}</b><small>tCO₂e</small></div>
      <div class="metric"><span>Indirect axis</span><b>{axes['indirect_tco2e']}</b><small>tCO₂e</small></div>
      <div class="metric"><span>Process axis</span><b>{axes['process_tco2e']}</b><small>tCO₂e</small></div>
      <div class="metric"><span>Precursor axis</span><b>{axes['precursor_tco2e']}</b><small>tCO₂e</small></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Item / installation</th><th>Component</th><th>Operands</th><th>Result / step</th></tr></thead>
      <tbody>{''.join(component_rows)}</tbody>
    </table></div>
    <p><code>{_escape(cbam['method'])}</code></p>
    <p><strong>{cbam['actual_data_scenario']['embedded_emissions_tco2e']} tCO₂e</strong> ·
    품목 중량 대사 <strong>{str(cbam['reconciliation']['mass_matches']).upper()}</strong> ·
    가중집약도 대사 <strong>{str(cbam['reconciliation']['intensity_matches']).upper()}</strong>.</p>
    <h3>Analyst-defined sensitivity</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Scenario</th><th>Factor</th><th>Certificate price</th><th>Third-country price</th><th>Exposure</th></tr></thead>
      <tbody>{sensitivity_rows}</tbody>
    </table></div>
    <p class="muted">이 값은 기술 인벤토리 기반 가격 민감도입니다. 공식 CBAM factor, 인증서 의무량,
    신고액 또는 지급액이 아닙니다. 전기·LNG는 배출계수와 배분근거가 없어 계산에 사용하지 않았습니다.</p>
  </section>

  <section class="panel forest">
    <h2>5. Synthetic forest reference-mask evaluation</h2>
    <div class="grid">
      <div class="metric"><span>TP / FP</span><b>{confusion['tp']} / {confusion['fp']}</b></div>
      <div class="metric"><span>FN / TN</span><b>{confusion['fn']} / {confusion['tn']}</b></div>
      <div class="metric"><span>F1</span><b>{_fmt_metric(forest_metrics['f1'])}</b></div>
      <div class="metric"><span>IoU</span><b>{_fmt_metric(forest_metrics['iou'])}</b></div>
    </div>
    <p class="muted">6×6 합성 red/NIR 격자와 별도 reference mask의 코드 경로 검증입니다.
    실제 위성 타일, 모델 일반화 성능 또는 EUDR 적합성 판정이 아닙니다.</p>
    {forest_svg}
  </section>

  <section class="panel">
    <h2>6. Reproduction inputs</h2>
    <p class="muted">산출물에는 시각 대신 입력 byte 수와 SHA-256을 고정합니다.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Input</th><th>Bytes</th><th>SHA-256</th></tr></thead>
      <tbody>{input_rows}</tbody>
    </table></div>
    <p><code>./scripts/verify_release.sh</code>는 wheel을 만들고 저장소 밖에서 설치·실행한 뒤
    공개 golden artifact와 바이트 단위로 비교합니다.</p>
  </section>

  <section class="panel"><h2>Boundaries</h2><ul>{boundaries}</ul></section>
  <footer>EcoGuard · Team UniHana · 3 members · 2026 · public reproducibility package</footer>
</main>
</body>
</html>
"""
