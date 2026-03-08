from importlib import import_module
import numpy as np


def load_plotting_module():
    return import_module("metabolomics.utils.plotting")


class TestPlottingBatchMemberships:
    def test_normalize_batch_memberships_splits_semicolon_labels(self):
        plotting = load_plotting_module()

        memberships = plotting.normalize_batch_memberships(
            batch_labels=["A", "A; B", "B;C", " C "]
        )

        assert memberships == [
            ("A",),
            ("A", "B"),
            ("B", "C"),
            ("C",),
        ]

    def test_build_batch_group_indices_omits_composite_labels(self):
        plotting = load_plotting_module()

        group_indices = plotting.build_batch_group_indices(
            [
                ("A",),
                ("A", "B"),
                ("B", "C"),
                ("C",),
            ]
        )

        assert list(group_indices) == ["A", "B", "C"]
        assert group_indices["A"] == [0, 1]
        assert group_indices["B"] == [1, 2]
        assert group_indices["C"] == [2, 3]


class TestPlottingSampleTypeOrdering:
    def test_visible_sample_types_keep_normal_distinct(self):
        plotting = load_plotting_module()

        visible_types = plotting.get_visible_sample_types(
            ["Control", "Normal", "Exposure", "QC", "Control"]
        )

        assert visible_types[0] == "QC"
        assert "Normal" in visible_types
        assert "Control" in visible_types
        assert "Exposure" in visible_types


class TestRealSamplePlotting:
    def test_build_sample_type_group_indices_excludes_qc_and_preserves_dynamic_groups(self):
        plotting = load_plotting_module()

        group_indices = plotting.build_sample_type_group_indices(
            ["QC", "Normal", "Benign", "Exposure", "Normal", "Exposure"],
            exclude_types={"QC"},
        )

        assert list(group_indices) == ["Normal", "Control", "Exposure"]
        assert group_indices["Normal"] == [1, 4]
        assert group_indices["Control"] == [2]
        assert group_indices["Exposure"] == [3, 5]

    def test_real_sample_pca_plot_uses_all_samples_and_only_large_group_ellipses(self, tmp_path):
        plotting = load_plotting_module()

        scores_left = np.array(
            [
                [0.0, 0.0],
                [0.2, 0.1],
                [0.4, -0.1],
                [2.0, 0.0],
                [2.2, 0.2],
                [2.4, -0.2],
                [4.0, 0.0],
                [4.2, 0.2],
            ]
        )
        scores_right = scores_left + 0.1
        sample_names = [f"S{i}" for i in range(len(scores_left))]
        sample_types = [
            "QC",
            "Normal",
            "Normal",
            "Normal",
            "Benign",
            "Benign",
            "Exposure",
            "Exposure",
        ]

        fig, (ax_left, _) = plotting.plot_pca_comparison_real_sample_style(
            scores_left,
            scores_right,
            np.array([0.55, 0.25]),
            np.array([0.50, 0.20]),
            sample_names,
            sample_types,
            output_path=tmp_path / "real_sample_pca.png",
        )

        sample_legend = ax_left.artists[0]
        sample_labels = [text.get_text() for text in sample_legend.get_texts()]
        assert "QC" not in sample_labels
        assert sample_labels == ["Normal", "Control", "Exposure"]

        ellipse_legend = ax_left.get_legend()
        ellipse_labels = [text.get_text() for text in ellipse_legend.get_texts()]
        assert "95% CI (All Samples)" in ellipse_labels
        assert "95% CI (Normal)" in ellipse_labels
        assert "95% CI (Control)" not in ellipse_labels
        assert "95% CI (Exposure)" not in ellipse_labels

        fig.clf()
