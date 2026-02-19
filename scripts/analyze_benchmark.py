
import json
import collections
from pathlib import Path

def analyze_benchmark(cases_path):
    with open(cases_path, 'r') as f:
        cases = [json.loads(line) for line in f if line.strip()]

    total_cases = len(cases)
    pass_count = sum(1 for c in cases if c.get('expected_pass') is True)
    fail_count = sum(1 for c in cases if c.get('expected_pass') is False)
    unlabeled_count = sum(1 for c in cases if c.get('expected_pass') is None)

    fail_reasons = collections.defaultdict(int)
    for c in cases:
        if c.get('expected_pass') is False:
            reasons = c.get('expected_fail_reasons', [])
            for r in reasons:
                fail_reasons[r] += 1

    product_spec_counts = collections.defaultdict(int)
    for c in cases:
        key = f"p{c.get('product_id')}-v{c.get('spec_version_id')}"
        product_spec_counts[key] += 1

    content_hashes = collections.defaultdict(list)
    for c in cases:
        h = c.get('content_hash')
        if h:
            content_hashes[h].append(c.get('case_id'))

    duplicates = {h: ids for h, ids in content_hashes.items() if len(ids) > 1}

    print(f"Total Cases: {total_cases}")
    print(f"Pass: {pass_count} ({pass_count/total_cases:.1%})")
    print(f"Fail: {fail_count} ({fail_count/total_cases:.1%})")
    print(f"Unlabeled: {unlabeled_count} ({unlabeled_count/total_cases:.1%})")

    print("\nFailure Reasons:")
    for r, count in sorted(fail_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {r}: {count}")

    print("\nProduct/Spec Distribution:")
    for key, count in sorted(product_spec_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {key}: {count}")

    print("\nDuplicates:")
    if duplicates:
        for h, ids in duplicates.items():
            print(f"  Hash {h[:8]}: {ids}")
    else:
        print("  None")

if __name__ == "__main__":
    analyze_benchmark('artifacts/validation_benchmark/cases.jsonl')
