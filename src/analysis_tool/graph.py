from dataclasses import dataclass, field

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class GraphEdge:
    from_agent: str
    to_agent: str
    message_count: int = 0
    message_types: set[str] = field(default_factory=set[str])


@dataclass
class Graph:
    nodes: set[str] = field(default_factory=set[str])
    edges: list[GraphEdge] = field(default_factory=list[GraphEdge])


def build_collaboration_graph(events: list[UnifiedEvent]) -> Graph:
    """Extract agent communication graph from message_send events."""
    graph = Graph()

    edge_map: dict[tuple[str, str], GraphEdge] = {}

    for event in events:
        if event.type != EventType.MESSAGE_SEND:
            continue

        from_agent = event.data.get("from", event.agent_id)
        to_agent = event.data.get("to", "")

        if not from_agent or not to_agent:
            continue

        graph.nodes.add(from_agent)
        graph.nodes.add(to_agent)

        key = (from_agent, to_agent)
        if key not in edge_map:
            edge_map[key] = GraphEdge(from_agent=from_agent, to_agent=to_agent)

        edge = edge_map[key]
        edge.message_count += 1
        msg_type = event.data.get("message_type", "message")
        edge.message_types.add(msg_type)

    graph.edges = list(edge_map.values())
    return graph


def to_mermaid(graph: Graph) -> str:
    """Render collaboration graph as Mermaid markup."""
    lines = ["graph TD"]

    def node_id(name: str) -> str:
        return name.replace("-", "").replace("@", "").replace(".", "")

    for node in sorted(graph.nodes):
        label = node.split("@")[0] if "@" in node else node
        lines.append(f"    {node_id(node)}[{label}]")

    for edge in graph.edges:
        types = ", ".join(sorted(edge.message_types))
        lines.append(
            f"    {node_id(edge.from_agent)} -->|"
            f"{edge.message_count} msg [{types}]| "
            f"{node_id(edge.to_agent)}"
        )

    return "\n".join(lines) + "\n"
