"""The interview state graph (LLD §5.2).

Topology (fixed):
    set_conditional_entry_point(entry_router)   # greet | extract
    greet            -> ask
    extract          -> update_coverage
    update_coverage  -> route -> {ask | confirm}
    ask              -> END    # pause: hand control back to the user
    confirm          -> END

Pause = END. The next user turn re-invokes from the entry router and resumes from
the Postgres checkpoint (state is loaded, not execution position — there is no
long-lived interrupt).

`build_builder()` returns the un-compiled graph so tests can compile it with an
in-memory checkpointer. The app compiles it once at startup against a dedicated
async psycopg pool (OQ-L3: dedicated, not the SQLAlchemy/asyncpg pool).
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent import nodes
from app.agent.state import InterviewState
from app.config import settings


def build_builder() -> StateGraph:
    builder = StateGraph(InterviewState)
    builder.add_node("greet", nodes.greet_node)
    builder.add_node("extract", nodes.extract_node)
    builder.add_node("update_coverage", nodes.coverage_node)
    builder.add_node("ask", nodes.ask_node)
    builder.add_node("confirm", nodes.confirm_node)

    builder.set_conditional_entry_point(nodes.entry_router, {"greet": "greet", "extract": "extract"})
    builder.add_edge("greet", "ask")
    builder.add_edge("extract", "update_coverage")
    builder.add_conditional_edges("update_coverage", nodes.route, {"ask": "ask", "confirm": "confirm"})
    builder.add_edge("ask", END)
    builder.add_edge("confirm", END)
    return builder


def compile_graph(checkpointer):
    """Compile the graph against any checkpointer (Postgres in prod, memory in tests)."""
    return build_builder().compile(checkpointer=checkpointer)


# --- App lifecycle: a dedicated async psycopg pool for the checkpointer ------

_pool = None
_graph = None


def _psycopg_dsn() -> str:
    """Postgres DSN for psycopg (the checkpointer), derived from the app's URL.

    The app uses `postgresql+asyncpg://…` (SQLAlchemy); psycopg wants a plain
    `postgresql://…` DSN, so we strip the driver suffix.
    """
    return settings.database_url.replace("+asyncpg", "")


async def init_agent() -> None:
    """Open the checkpointer pool, create its tables (idempotent), compile the graph.

    Called once from the FastAPI lifespan on startup.
    """
    global _pool, _graph
    if _graph is not None:
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    _pool = AsyncConnectionPool(
        conninfo=_psycopg_dsn(),
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _pool.open()
    saver = AsyncPostgresSaver(_pool)
    await saver.setup()  # creates checkpoints/checkpoint_writes/… if absent (idempotent)
    _graph = compile_graph(saver)


async def close_agent() -> None:
    global _pool, _graph
    if _pool is not None:
        await _pool.close()
    _pool = None
    _graph = None


def get_graph():
    if _graph is None:
        raise RuntimeError("agent graph not initialized; call init_agent() at startup")
    return _graph
