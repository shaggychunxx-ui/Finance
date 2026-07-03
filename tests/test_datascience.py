import unittest
from unittest.mock import patch

from agents.datascience.expert import BENCHMARK, DataScienceExpert


class DataScienceExpertTests(unittest.TestCase):
    def test_analyze_raises_when_benchmark_data_unavailable(self) -> None:
        expert = DataScienceExpert(delay_seconds=0)

        with patch.object(expert, "_fetch_closes", return_value=[]):
            with self.assertRaisesRegex(
                RuntimeError,
                f"Unable to fetch {BENCHMARK} data for data science analysis",
            ):
                expert.analyze()


if __name__ == "__main__":
    unittest.main()
