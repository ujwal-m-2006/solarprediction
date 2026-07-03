"""Chart generation for the prediction report."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")


def plot_flare_probabilities(top_regions, out_name="flare_probability_by_region.png"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    labels = [f"AR{r['region']}\n{r['location']}" for r in top_regions]
    c_vals = [r["blended_estimate_pct"]["C"] or 0 for r in top_regions]
    m_vals = [r["blended_estimate_pct"]["M"] or 0 for r in top_regions]
    x_vals = [r["blended_estimate_pct"]["X"] or 0 for r in top_regions]

    x = range(len(labels))
    width = 0.25
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([i - width for i in x], c_vals, width, label="C-class", color="#f4c542")
    ax.bar(list(x), m_vals, width, label="M-class", color="#e8703a")
    ax.bar([i + width for i in x], x_vals, width, label="X-class", color="#c0392b")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("24h flare probability (%)")
    ax.set_title("Blended 24h Flare Probability by Active Region")
    ax.legend()
    ax.set_ylim(0, 100)
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, out_name)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def plot_cme_arrival_timeline(cme_predictions, out_name="cme_arrival_timeline.png"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    valid = [c for c in cme_predictions if c["arrival"].get("transit_hours_best") is not None]
    if not valid:
        return None

    labels = [f"{c['flare_class']}\n{c['flare_peak_time'][5:16]}" for c in valid]
    best = [c["arrival"]["transit_hours_best"] for c in valid]
    low = [c["arrival"]["transit_hours_low"] for c in valid]
    high = [c["arrival"]["transit_hours_high"] for c in valid]
    err_low = [b - l for b, l in zip(best, low)]
    err_high = [h - b for b, h in zip(best, high)]

    fig, ax = plt.subplots(figsize=(9, 5))
    y = range(len(labels))
    ax.errorbar(best, y, xerr=[err_low, err_high], fmt="o", color="#2c3e50",
                ecolor="#7f8c8d", elinewidth=2, capsize=4, markersize=8)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.set_xlabel("Estimated Earth transit time (hours)")
    ax.set_title("CME Earth-Arrival Estimate (Drag-Based Model, uncertainty band)")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, out_name)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
