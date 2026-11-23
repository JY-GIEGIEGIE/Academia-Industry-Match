import unittest

from scripts.data.s08_analysis import _md_escape, _metric_row, _select_error_cases


class S08AnalysisTests(unittest.TestCase):
    def test_metric_row_zero(self):
        row = _metric_row("B0", {"recall10": 0, "prec5": 0, "ndcg10": 0, "mrr": 0}, 0)
        self.assertIn("| B0 | — | — | — | — | 0 |", row)

    def test_metric_row_values(self):
        row = _metric_row(
            "B2",
            {"recall10": 1.0, "prec5": 0.8, "ndcg10": 0.5, "mrr": 0.25},
            2,
        )
        self.assertIn("| B2 | 0.500 | 0.400 | 0.250 | 0.125 | 2 |", row)

    def test_md_escape(self):
        self.assertEqual(_md_escape("a|b\nc"), "a\\|b c")

    def test_error_cases_select_five_each(self):
        ranked = []
        for i in range(5):
            # rank 1 is non-relevant; the only relevant item is outside Top-10
            ranked.append(
                (
                    f"q{i}",
                    [f"fp{i}", "x", "y", "z", "u", "v", "w", "r", "s", "t"],
                    {f"fp{i}": 0, f"fn{i}": 1},
                    [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05],
                )
            )
        fps, fns = _select_error_cases(ranked, {})
        self.assertEqual(len(fps), 5)
        self.assertEqual(len(fns), 5)
        self.assertTrue(all(r["type"] == "FP" for r in fps))
        self.assertTrue(all(r["type"] == "FN" for r in fns))


if __name__ == "__main__":
    unittest.main()
