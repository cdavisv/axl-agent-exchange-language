"""Verify regenerated full results against committed tokenizer summaries."""
import argparse
import json
from pathlib import Path


def verify(result, expected):
    observations = result['observations']
    assert len(observations) == 608
    assert result['checks'] == 1824
    assert len({row['case_id'] for row in observations}) == 38
    for row in observations:
        assert row['costs']['hybrid_wire']['wire'] == min(
            row['costs'][mode]['wire'] for mode in ('typed_rows', 'guarded_packed_json')
        )
        assert row['choices']['hybrid_context'] in ('typed_rows', 'guarded_packed_json')
    for horizon, modes in result['summary'].items():
        for mode, metrics in modes.items():
            for metric, value in metrics.items():
                assert value == sum(row['costs'][mode][metric] for row in observations if row['turn'] < int(horizon))
    for key in ('checks', 'summary', 'corpus_sha256', 'tokenizer_sha256'):
        assert result[key] == expected[key], key
    counts = {
        mode: {choice: sum(row['choices'][mode] == choice for row in observations)
               for choice in ('guarded_packed_json', 'typed_rows')}
        for mode in ('hybrid_wire', 'hybrid_context')
    }
    assert counts == expected['selection_counts']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    parser.add_argument('--tokenizer-name', choices=('gemma', 'qwen'), required=True)
    args = parser.parse_args()
    summaries = json.loads(Path(__file__).with_name('summary.json').read_text())
    verify(json.loads(args.result.read_text()), summaries[args.tokenizer_name])
    print('608 observations, selection counts, aggregates and recorded summary verified')
