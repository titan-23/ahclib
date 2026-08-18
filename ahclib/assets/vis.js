window.dashAgGridFunctions = window.dashAgGridFunctions || {};

window.dashAgGridFunctions.caseKeyNavigation = (params, setGridProps) => {
    const event = params.event;
    const tagName = event?.target?.tagName;
    if (
        !event ||
        !["j", "k"].includes(event.key) ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(tagName)
    ) {
        return;
    }

    const offset = event.key === "j" ? 1 : -1;
    const nextIndex = params.node.rowIndex + offset;
    const nextNode = params.api.getDisplayedRowAtIndex(nextIndex);
    if (!nextNode) {
        return;
    }

    event.preventDefault();
    nextNode.setSelected(true, true);
    params.api.ensureIndexVisible(nextIndex, "middle");
    setGridProps({selectedRows: {ids: [String(nextNode.id)]}});
};
