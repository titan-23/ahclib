import matplotlib.pyplot as plt


def showfig(x, y, gtype="plot", xlabel="", ylabel="", title="", savetitle=""):
    fig, ax = plt.subplots()

    A = [d[0] for d in y]
    B = [d[1] for d in y]
    ax.plot(x, A, linewidth=2, label="")

    # # Plot A on the left y-axis
    # ax.plot(x, A, linewidth=2, label="A")
    # ax.set_xlabel(xlabel)
    # ax.set_ylabel("A values" if not ylabel else ylabel + " (A)", color="blue")
    # ax.tick_params(axis="y", labelcolor="blue")

    # # Create a secondary y-axis for B
    # ax2 = ax.twinx()
    # ax2.plot(x, B, linewidth=1, color="red", label="B")
    # ax2.set_ylabel("B values" if not ylabel else ylabel + " (B)", color="red")
    # ax2.tick_params(axis="y", labelcolor="red")

    ax.set_xlim()
    ax.set_ylim()

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    ax.minorticks_on()
    ax.tick_params(which="both", top="on", right="on", direction="in")
    ax.grid(which="major", axis="both")

    ax.legend(loc="lower right")
    # plt.show()
    if savetitle:
        plt.savefig(f"{savetitle}")


data = []
with open("./out.txt", "r", encoding="utf-8") as f:
    for line in f:
        try:
            a, b = map(int, line.split())
            data.append((a, b))
        except Exception as e:
            break

x = range(1, len(data) + 1)
showfig(
    x,
    data,
    xlabel="turn",
    ylabel="beam width",
    title="beam_width",
    savetitle="a.png",
)
