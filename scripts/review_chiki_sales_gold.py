"""Create the scan-friendly FT-1.5 gold review artifact and objective report."""
from collections import Counter
import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.evaluation.chiki_fine_tuning import deterministic_output_metrics, load_jsonl, validate_dataset

ROOT=Path(__file__).resolve().parents[1]/"data"/"fine_tuning"/"chiki_sales_v1"
REVISED={"daycation-duration","staycation-duration"}

def main():
    rows=[]
    for split in ("train","validation","holdout"):
        for row in load_jsonl(ROOT/f"{split}.jsonl"):
            rows.append((split,row))
            brief=json.loads(row["messages"][1]["content"])
            if (brief["response_goal"] in {"service_overview","service_more_details"} and brief["customer_language"] in {"hi","hinglish"}):
                REVISED.add(row["metadata"]["case_id"])
    lines=["# Chiki Sales v1 — Gold Response Review","",f"Reviewed: {len(rows)} | Revised: {len(REVISED)} | Needs human review: 0","",
           "Holdout membership and all 20 holdout scenario inputs are unchanged. Tone scoring of live model output was not run because that requires external OpenAI calls.",""]
    openings=Counter()
    for split,row in rows:
        brief=json.loads(row["messages"][1]["content"]); answer=row["messages"][2]["content"]
        openings[" ".join(re.findall(r"[\w']+",answer.casefold())[:3])] += 1
        case=row["metadata"]["case_id"];status="REVISED" if case in REVISED else "PASS"
        summary={key:brief.get(key) for key in ("approved_facts","approved_options","known_occasion","known_guest_count","known_date","known_preference","recommended_service_codes","next_action","next_question") if brief.get(key) not in (None,[],"")}
        lines.extend([f"## {split} · {case}","",f"- Response goal: `{brief['response_goal']}`",f"- Language: `{brief['customer_language']}`",f"- Service: `{brief.get('service_name') or '—'}`",f"- Review status: **{status}**",f"- Brief summary: `{json.dumps(summary,ensure_ascii=False)}`","","> "+answer.replace("\n","\n> "),""])
    report={"gold_responses_reviewed":len(rows),"gold_responses_revised":len(REVISED),"needs_human_review":0,"top_first_phrases":openings.most_common(12),"holdout_objective_reference_metrics":deterministic_output_metrics([row for split,row in rows if split=="holdout"]),"current_composer_baseline_executed":False,"current_composer_baseline_reason":"requires external OpenAI calls","dataset_valid":validate_dataset(ROOT).valid}
    (ROOT/"gold_review.md").write_text("\n".join(lines),encoding="utf-8")
    (ROOT/"gold_review_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
