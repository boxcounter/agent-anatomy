from dataclasses import dataclass, field

from agent_anatomy.models import EventType, UnifiedEvent
from agent_anatomy.roles import AgentRole, Topology, canonical_id


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


_ROLE_STYLE: dict[AgentRole, str] = {
    AgentRole.LEAD: "fill:#d32f2f,color:#fff,stroke:#b71c1c",
    AgentRole.TEAMMATE: "fill:#1976d2,color:#fff,stroke:#0d47a1",
    AgentRole.SUBAGENT: "fill:#388e3c,color:#fff,stroke:#1b5e20",
    AgentRole.ROOT: "fill:#455a64,color:#fff,stroke:#263238",
    AgentRole.PHASE: "fill:#f59e0b,color:#222,stroke:#b45309",
    AgentRole.UNKNOWN: "fill:#9e9e9e,color:#fff,stroke:#616161",
}


def to_mermaid(graph: Graph, topology: Topology | None = None) -> str:
    """Render the collaboration graph as Mermaid markup.

    Solid edges (`-->`) are spawn/delegation; dashed edges (`-.->`) are
    messages. Nodes are coloured by role when a topology is supplied. Without
    a topology it degrades to a labelled message-only graph.
    """
    lines = ["graph TD"]
    lines.append("    %% solid = spawns (delegation), dashed = messages")

    def node_id(name: str) -> str:
        return "n_" + "".join(c if c.isalnum() else "_" for c in name)

    # Collect every node: message participants plus all profiled agents.
    node_set: set[str] = set(graph.nodes)
    if topology is not None:
        node_set |= set(topology.profiles)

    for node in sorted(node_set):
        if topology is not None:
            profile = topology.profile(node)
            label = profile.display_name if profile else node
            role = profile.role if profile else AgentRole.UNKNOWN
            lines.append(f'    {node_id(node)}["{_escape(label)}"]:::{role.value}')
        else:
            label = node.split("@")[0] if "@" in node else node
            lines.append(f'    {node_id(node)}["{_escape(label)}"]')

    # Spawn edges (solid) — the delegation tree.
    if topology is not None:
        for parent, children in sorted(topology.spawn_children.items()):
            for child in children:
                lines.append(f"    {node_id(parent)} -->|spawns| {node_id(child)}")

    # Message edges (dashed) — who talked to whom.
    for edge in graph.edges:
        types = ", ".join(sorted(edge.message_types))
        lines.append(
            f"    {node_id(edge.from_agent)} -.->|"
            f"{edge.message_count} msg: {types}| "
            f"{node_id(edge.to_agent)}"
        )

    if topology is not None:
        for role, style in _ROLE_STYLE.items():
            lines.append(f"    classDef {role.value} {style}")

    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    """Make a label safe inside a Mermaid `["..."]` node."""
    return text.replace('"', "'").replace("\n", " ")


def to_force_data(graph: Graph, topology: Topology) -> dict[str, list[dict[str, object]]]:
    """Build node/link data for the D3 force graph in report.html.

    Nodes are every profiled agent (coloured by role). Links are spawn edges
    (delegation tree) plus message edges (collaboration).
    """
    nodes: list[dict[str, object]] = []
    node_ids: set[str] = set()
    for cid, p in topology.profiles.items():
        nodes.append({
            "id": cid,
            "label": p.display_name,
            "role": p.role.value,
            "agent_type": p.agent_type,
            "events": p.event_count,
        })
        node_ids.add(cid)

    links: list[dict[str, object]] = []
    for parent, children in topology.spawn_children.items():
        for child in children:
            if parent in node_ids and child in node_ids:
                links.append({"source": parent, "target": child, "kind": "spawn", "label": "spawns"})

    for edge in graph.edges:
        src = canonical_id(edge.from_agent)
        dst = canonical_id(edge.to_agent)
        if src in node_ids and dst in node_ids:
            types = ", ".join(sorted(edge.message_types))
            links.append({
                "source": src, "target": dst, "kind": "message",
                "label": f"{edge.message_count} msg: {types}",
            })

    return {"nodes": nodes, "links": links}


# Keep canonical_id importable from here for callers that already depend on graph.
__all__ = [
    "Graph", "GraphEdge", "build_collaboration_graph", "to_mermaid", "to_force_data", "canonical_id",
]
