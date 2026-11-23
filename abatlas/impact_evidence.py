"""入口の根拠ファイルと、変更箇所へ届く前回の呼び出し経路。"""

from pathlib import Path


def references(node):
    """主張に付いた根拠と定義位置。I/O の資源名には file という項目もある。"""
    if isinstance(node, dict):
        for source in [node.get("source"), *node.get("evidence", [])]:
            if isinstance(source, dict) and "file" in source:
                # その OS の読み方で読んでから、Git の一覧と同じ「/」区切りにする
                yield Path(source["file"]).as_posix()
        for child in node.values():
            yield from references(child)
    elif isinstance(node, list):
        for child in node:
            yield from references(child)


def checkpoints(result, files):
    frames = {frame["id"]: frame for frame in result["callstack"]}
    points = []
    for frame in frames.values():
        hits = files.intersection(references(frame))
        if not hits:
            continue
        chain = []
        seen = set()
        current = frame
        while current and current["id"] not in seen:
            seen.add(current["id"])
            chain.append(current["name"])
            current = frames.get(current.get("caller"))
        points.append(
            {
                "route": list(reversed(chain)),
                "source": frame["source"],
                "files": sorted(hits),
            }
        )
    return points


def linked_entries(result):
    return {
        link["entry_id"]
        for frame in result["callstack"]
        for link in frame.get("links", [])
        if link.get("entry_id")
    }
