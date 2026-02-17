
import json
import collections

def analyze_disagreements(raw_path):
    with open(raw_path, 'r') as f:
        rows = [json.loads(line) for line in f if line.strip()]

    # Group by case_id
    cases = collections.defaultdict(dict)
    for row in rows:
        cases[row['case_id']][row['mode']] = row

    disagreements = []
    for case_id, modes in cases.items():
        det = modes.get('deterministic', {}).get('predicted_pass')
        llm = modes.get('llm', {}).get('predicted_pass')
        hyb = modes.get('hybrid', {}).get('predicted_pass')

        if len(set([det, llm, hyb])) > 1:
            disagreements.append({
                'case_id': case_id,
                'story_title': modes['deterministic'].get('result', {}).get('story', {}).get('title', 'Unknown'), # access might be different
                'deterministic': det,
                'llm': llm,
                'hybrid': hyb,
                'det_reasons': modes.get('deterministic', {}).get('predicted_reason_codes', []),
                'llm_reasons': modes.get('llm', {}).get('predicted_reason_codes', []),
                'hyb_reasons': modes.get('hybrid', {}).get('predicted_reason_codes', [])
            })

    print(f"Found {len(disagreements)} disagreements:")
    for d in disagreements:
        print(f"\nCase: {d['case_id']}")
        print(f"  Det: {d['deterministic']} {d['det_reasons']}")
        print(f"  LLM: {d['llm']} {d['llm_reasons']}")
        print(f"  Hyb: {d['hybrid']} {d['hyb_reasons']}")

if __name__ == "__main__":
    analyze_disagreements('artifacts/validation_eval/raw_20260216_210438.jsonl')
