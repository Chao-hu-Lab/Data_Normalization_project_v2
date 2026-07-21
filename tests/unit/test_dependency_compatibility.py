from matplotlib.figure import Figure


def test_matplotlib_supports_boxplot_labels_used_by_frozen_processors():
    axes = Figure().subplots()
    axes.boxplot([[1.0, 2.0]], labels=["Feature"])
